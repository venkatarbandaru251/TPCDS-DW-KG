{{ config(materialized='table', schema='silver') }}
-- Indexes + table storage params applied post-build by ingestion/run_pipeline.py
-- (dbt post_hooks are dropped by the table-swap rename in dbt-postgres 1.10).

-- Channel-agnostic fact of all sales: store, catalog, web.
-- Column names normalized so marts don't care which channel a row came from.

select
    'store'::text       as channel,
    ss_sold_date_sk     as sold_date_sk,
    ss_sold_time_sk     as sold_time_sk,
    ss_item_sk          as item_sk,
    ss_customer_sk      as customer_sk,
    ss_cdemo_sk         as cdemo_sk,
    ss_hdemo_sk         as hdemo_sk,
    ss_addr_sk          as addr_sk,
    ss_store_sk         as location_sk,
    ss_promo_sk         as promo_sk,
    ss_ticket_number    as order_number,
    ss_quantity         as quantity,
    ss_wholesale_cost   as wholesale_cost,
    ss_list_price       as list_price,
    ss_sales_price      as sales_price,
    ss_ext_discount_amt as ext_discount_amt,
    ss_ext_sales_price  as ext_sales_price,
    ss_ext_wholesale_cost as ext_wholesale_cost,
    ss_ext_list_price   as ext_list_price,
    ss_ext_tax          as ext_tax,
    ss_coupon_amt       as coupon_amt,
    ss_net_paid         as net_paid,
    ss_net_paid_inc_tax as net_paid_inc_tax,
    ss_net_profit       as net_profit
from {{ ref('fact_store_sales') }}

union all

select
    'catalog'::text     as channel,
    cs_sold_date_sk     as sold_date_sk,
    cs_sold_time_sk     as sold_time_sk,
    cs_item_sk          as item_sk,
    cs_bill_customer_sk as customer_sk,
    cs_bill_cdemo_sk    as cdemo_sk,
    cs_bill_hdemo_sk    as hdemo_sk,
    cs_bill_addr_sk     as addr_sk,
    cs_call_center_sk   as location_sk,
    cs_promo_sk         as promo_sk,
    cs_order_number     as order_number,
    cs_quantity         as quantity,
    cs_wholesale_cost   as wholesale_cost,
    cs_list_price       as list_price,
    cs_sales_price      as sales_price,
    cs_ext_discount_amt as ext_discount_amt,
    cs_ext_sales_price  as ext_sales_price,
    cs_ext_wholesale_cost as ext_wholesale_cost,
    cs_ext_list_price   as ext_list_price,
    cs_ext_tax          as ext_tax,
    cs_coupon_amt       as coupon_amt,
    cs_net_paid         as net_paid,
    cs_net_paid_inc_tax as net_paid_inc_tax,
    cs_net_profit       as net_profit
from {{ ref('fact_catalog_sales') }}

union all

select
    'web'::text         as channel,
    ws_sold_date_sk     as sold_date_sk,
    ws_sold_time_sk     as sold_time_sk,
    ws_item_sk          as item_sk,
    ws_bill_customer_sk as customer_sk,
    ws_bill_cdemo_sk    as cdemo_sk,
    ws_bill_hdemo_sk    as hdemo_sk,
    ws_bill_addr_sk     as addr_sk,
    ws_web_site_sk      as location_sk,
    ws_promo_sk         as promo_sk,
    ws_order_number     as order_number,
    ws_quantity         as quantity,
    ws_wholesale_cost   as wholesale_cost,
    ws_list_price       as list_price,
    ws_sales_price      as sales_price,
    ws_ext_discount_amt as ext_discount_amt,
    ws_ext_sales_price  as ext_sales_price,
    ws_ext_wholesale_cost as ext_wholesale_cost,
    ws_ext_list_price   as ext_list_price,
    ws_ext_tax          as ext_tax,
    ws_coupon_amt       as coupon_amt,
    ws_net_paid         as net_paid,
    ws_net_paid_inc_tax as net_paid_inc_tax,
    ws_net_profit       as net_profit
from {{ ref('fact_web_sales') }}
