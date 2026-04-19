{{ config(materialized='table', schema='gold') }}
-- Indexes applied post-build by ingestion/run_pipeline.py

-- Monthly side-by-side of store vs catalog vs web. One row per (year, month);
-- channels pivoted to columns so BI tools can bar-chart them directly.

with monthly as (
    select
        d.d_year,
        d.d_moy,
        u.channel,
        count(distinct u.order_number) as order_count,
        sum(u.quantity)                as quantity,
        sum(u.ext_sales_price)         as gross_sales,
        sum(u.net_paid)                as net_sales,
        sum(u.net_profit)              as net_profit
    from {{ ref('int_sales_unified') }} u
    join {{ ref('dim_date_dim') }} d on d.d_date_sk = u.sold_date_sk
    where u.sold_date_sk is not null
    group by d.d_year, d.d_moy, u.channel
)
select
    d_year,
    d_moy,
    -- Store
    max(case when channel='store'   then order_count end) as store_orders,
    max(case when channel='store'   then quantity end)    as store_quantity,
    max(case when channel='store'   then gross_sales end) as store_gross_sales,
    max(case when channel='store'   then net_sales end)   as store_net_sales,
    max(case when channel='store'   then net_profit end)  as store_net_profit,
    -- Catalog
    max(case when channel='catalog' then order_count end) as catalog_orders,
    max(case when channel='catalog' then quantity end)    as catalog_quantity,
    max(case when channel='catalog' then gross_sales end) as catalog_gross_sales,
    max(case when channel='catalog' then net_sales end)   as catalog_net_sales,
    max(case when channel='catalog' then net_profit end)  as catalog_net_profit,
    -- Web
    max(case when channel='web'     then order_count end) as web_orders,
    max(case when channel='web'     then quantity end)    as web_quantity,
    max(case when channel='web'     then gross_sales end) as web_gross_sales,
    max(case when channel='web'     then net_sales end)   as web_net_sales,
    max(case when channel='web'     then net_profit end)  as web_net_profit,
    -- Totals
    sum(order_count) as total_orders,
    sum(quantity)    as total_quantity,
    sum(gross_sales) as total_gross_sales,
    sum(net_sales)   as total_net_sales,
    sum(net_profit)  as total_net_profit
from monthly
group by d_year, d_moy
