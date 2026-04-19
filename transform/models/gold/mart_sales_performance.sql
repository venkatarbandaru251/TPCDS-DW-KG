{{ config(materialized='table', schema='gold') }}
-- Indexes applied post-build by ingestion/run_pipeline.py

-- Daily sales + returns rollup per channel. Monthly rollups are a simple
-- GROUP BY on (sale_year, sale_month, channel) when the BA needs them.

with sales as (
    select
        sold_date_sk,
        channel,
        count(*)                    as line_item_count,
        count(distinct order_number) as order_count,
        sum(quantity)               as quantity_sold,
        sum(ext_sales_price)        as gross_sales,
        sum(ext_discount_amt)       as discount_amt,
        sum(ext_tax)                as tax_amt,
        sum(net_paid)               as net_sales,
        sum(net_profit)             as net_profit
    from {{ ref('int_sales_unified') }}
    where sold_date_sk is not null
    group by sold_date_sk, channel
),
returns as (
    select
        returned_date_sk,
        channel,
        count(distinct order_number) as return_order_count,
        sum(return_quantity)         as return_quantity,
        sum(return_amt)              as return_amt,
        sum(net_loss)                as return_net_loss
    from {{ ref('int_returns_unified') }}
    where returned_date_sk is not null
    group by returned_date_sk, channel
)
select
    d.d_date                  as sale_date,
    d.d_year                  as sale_year,
    d.d_moy                   as sale_month,
    d.d_dow                   as sale_dow,
    s.channel,
    s.line_item_count,
    s.order_count,
    s.quantity_sold,
    s.gross_sales,
    s.discount_amt,
    s.tax_amt,
    s.net_sales,
    s.net_profit,
    coalesce(r.return_order_count, 0) as return_order_count,
    coalesce(r.return_quantity, 0)    as return_quantity,
    coalesce(r.return_amt, 0)         as return_amt,
    coalesce(r.return_net_loss, 0)    as return_net_loss,
    case when s.gross_sales > 0
         then round((coalesce(r.return_amt, 0) / s.gross_sales)::numeric, 4)
         end                         as return_rate
from sales s
join {{ ref('dim_date_dim') }} d on d.d_date_sk = s.sold_date_sk
left join returns r
       on r.returned_date_sk = s.sold_date_sk
      and r.channel = s.channel
