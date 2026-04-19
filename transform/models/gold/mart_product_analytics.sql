{{ config(materialized='table', schema='gold') }}
-- Indexes applied post-build by ingestion/run_pipeline.py

-- One row per item: total + per-channel metrics, returns, rank.
-- Items with no sales appear with zeroed metrics and NULL rank.

with sales_by_item_channel as (
    select
        item_sk,
        channel,
        sum(quantity)        as quantity,
        sum(ext_sales_price) as gross_sales,
        sum(net_paid)        as net_sales,
        sum(net_profit)      as net_profit
    from {{ ref('int_sales_unified') }}
    where item_sk is not null
    group by item_sk, channel
),
per_item as (
    select
        item_sk,
        sum(quantity)    as total_quantity,
        sum(gross_sales) as total_gross_sales,
        sum(net_sales)   as total_net_sales,
        sum(net_profit)  as total_net_profit,
        max(case when channel='store'   then quantity end)    as store_quantity,
        max(case when channel='catalog' then quantity end)    as catalog_quantity,
        max(case when channel='web'     then quantity end)    as web_quantity,
        max(case when channel='store'   then gross_sales end) as store_gross_sales,
        max(case when channel='catalog' then gross_sales end) as catalog_gross_sales,
        max(case when channel='web'     then gross_sales end) as web_gross_sales
    from sales_by_item_channel
    group by item_sk
),
returns_by_item as (
    select
        item_sk,
        sum(return_quantity) as returned_quantity,
        sum(return_amt)      as returned_amt
    from {{ ref('int_returns_unified') }}
    where item_sk is not null
    group by item_sk
),
ranked as (
    select
        p.*,
        row_number() over (order by p.total_net_sales desc nulls last) as sales_rank,
        ntile(100)   over (order by p.total_net_sales desc nulls last) as sales_percentile
    from per_item p
)
select
    i.i_item_sk,
    i.i_item_id,
    i.i_product_name,
    i.i_brand,
    i.i_class,
    i.i_category,
    i.i_manufact,
    i.i_current_price,
    coalesce(r.total_quantity, 0)      as total_quantity,
    coalesce(r.total_gross_sales, 0)   as total_gross_sales,
    coalesce(r.total_net_sales, 0)     as total_net_sales,
    coalesce(r.total_net_profit, 0)    as total_net_profit,
    coalesce(r.store_quantity, 0)      as store_quantity,
    coalesce(r.catalog_quantity, 0)    as catalog_quantity,
    coalesce(r.web_quantity, 0)        as web_quantity,
    coalesce(r.store_gross_sales, 0)   as store_gross_sales,
    coalesce(r.catalog_gross_sales, 0) as catalog_gross_sales,
    coalesce(r.web_gross_sales, 0)     as web_gross_sales,
    coalesce(rt.returned_quantity, 0)  as returned_quantity,
    coalesce(rt.returned_amt, 0)       as returned_amt,
    case when r.total_quantity > 0
         then round((coalesce(rt.returned_quantity, 0)::numeric / r.total_quantity), 4)
         end                           as return_rate,
    r.sales_rank,
    r.sales_percentile
from {{ ref('dim_item') }} i
left join ranked r           on r.item_sk = i.i_item_sk
left join returns_by_item rt on rt.item_sk = i.i_item_sk
