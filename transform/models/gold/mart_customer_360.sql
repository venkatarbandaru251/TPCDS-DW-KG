{{ config(materialized='table', schema='gold') }}
-- Indexes applied post-build by ingestion/run_pipeline.py

-- One row per customer with LTV, RFM, and lifecycle segment.
-- Customers with no sales still appear (left join), with NULL metrics.
-- Recency is computed relative to the max sale date in the warehouse.

with sales_agg as (
    select
        customer_sk,
        min(sold_date_sk)               as first_sale_date_sk,
        max(sold_date_sk)               as last_sale_date_sk,
        count(distinct (channel || '|' || order_number)) as order_count,
        sum(quantity)                   as quantity_purchased,
        sum(ext_sales_price)            as gross_sales,
        sum(net_paid)                   as ltv_net_paid,
        sum(net_profit)                 as profit_total
    from {{ ref('int_sales_unified') }}
    where customer_sk is not null
      and sold_date_sk is not null
    group by customer_sk
),
returns_agg as (
    select
        customer_sk,
        sum(return_quantity) as returned_quantity,
        sum(return_amt)      as returned_amt
    from {{ ref('int_returns_unified') }}
    where customer_sk is not null
    group by customer_sk
),
reference_date as (
    select max(sold_date_sk) + 1 as today_sk
    from {{ ref('int_sales_unified') }}
),
scored as (
    select
        s.customer_sk,
        s.first_sale_date_sk,
        s.last_sale_date_sk,
        (rd.today_sk - s.last_sale_date_sk) as recency_days,
        s.order_count,
        s.quantity_purchased,
        s.gross_sales,
        s.ltv_net_paid,
        s.profit_total,
        r.returned_quantity,
        r.returned_amt,
        ntile(5) over (order by (rd.today_sk - s.last_sale_date_sk) desc) as r_quintile,
        ntile(5) over (order by s.order_count)                             as f_quintile,
        ntile(5) over (order by s.ltv_net_paid)                            as m_quintile
    from sales_agg s
    left join returns_agg r using (customer_sk)
    cross join reference_date rd
)
select
    c.c_customer_sk,
    c.c_customer_id,
    c.c_first_name,
    c.c_last_name,
    c.c_email_address,
    c.c_birth_year,
    c.c_preferred_cust_flag,
    cd.cd_gender,
    cd.cd_marital_status,
    cd.cd_education_status,
    ib.ib_lower_bound  as income_lower,
    ib.ib_upper_bound  as income_upper,
    s.first_sale_date_sk,
    s.last_sale_date_sk,
    s.recency_days,
    s.order_count,
    coalesce(s.quantity_purchased, 0) as quantity_purchased,
    coalesce(s.gross_sales, 0)        as gross_sales,
    coalesce(s.ltv_net_paid, 0)       as ltv_net_paid,
    coalesce(s.profit_total, 0)       as profit_total,
    coalesce(s.returned_quantity, 0)  as returned_quantity,
    coalesce(s.returned_amt, 0)       as returned_amt,
    case when s.gross_sales > 0
         then round((coalesce(s.returned_amt, 0) / s.gross_sales)::numeric, 4)
         end                          as return_rate,
    s.r_quintile,
    s.f_quintile,
    s.m_quintile,
    (s.r_quintile * 100 + s.f_quintile * 10 + s.m_quintile) as rfm_score,
    case
        when s.customer_sk is null                                      then 'No purchase'
        when s.r_quintile >= 4 and s.f_quintile >= 4 and s.m_quintile >= 4 then 'Champions'
        when s.r_quintile >= 4 and s.f_quintile >= 3                      then 'Loyal'
        when s.r_quintile <= 2 and s.m_quintile >= 4                      then 'At risk high-value'
        when s.r_quintile <= 2                                            then 'Hibernating'
        when s.f_quintile = 1                                             then 'New'
        else 'Active'
    end                                as segment
from {{ ref('dim_customer') }} c
left join scored s on s.customer_sk = c.c_customer_sk
left join {{ ref('dim_customer_demographics') }} cd on cd.cd_demo_sk = c.c_current_cdemo_sk
left join {{ ref('dim_household_demographics') }} hd on hd.hd_demo_sk = c.c_current_hdemo_sk
left join {{ ref('dim_income_band') }}            ib on ib.ib_income_band_sk = hd.hd_income_band_sk
