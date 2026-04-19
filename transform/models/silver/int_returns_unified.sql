{{ config(materialized='table', schema='silver') }}
-- Indexes applied post-build by ingestion/run_pipeline.py

-- Channel-agnostic fact of all returns: store, catalog, web.
-- For store, customer_sk = sr_customer_sk (only customer column present).
-- For catalog/web, customer_sk = *_refunded_customer_sk (original buyer,
-- matching the customer_sk convention used in int_sales_unified).

select
    'store'::text       as channel,
    sr_returned_date_sk as returned_date_sk,
    sr_return_time_sk   as returned_time_sk,
    sr_item_sk          as item_sk,
    sr_customer_sk      as customer_sk,
    sr_reason_sk        as reason_sk,
    sr_ticket_number    as order_number,
    sr_return_quantity  as return_quantity,
    sr_return_amt       as return_amt,
    sr_return_tax       as return_tax,
    sr_net_loss         as net_loss
from {{ ref('fact_store_returns') }}

union all

select
    'catalog'::text          as channel,
    cr_returned_date_sk      as returned_date_sk,
    cr_returned_time_sk      as returned_time_sk,
    cr_item_sk               as item_sk,
    cr_refunded_customer_sk  as customer_sk,
    cr_reason_sk             as reason_sk,
    cr_order_number          as order_number,
    cr_return_quantity       as return_quantity,
    cr_return_amount         as return_amt,
    cr_return_tax            as return_tax,
    cr_net_loss              as net_loss
from {{ ref('fact_catalog_returns') }}

union all

select
    'web'::text              as channel,
    wr_returned_date_sk      as returned_date_sk,
    wr_returned_time_sk      as returned_time_sk,
    wr_item_sk               as item_sk,
    wr_refunded_customer_sk  as customer_sk,
    wr_reason_sk             as reason_sk,
    wr_order_number          as order_number,
    wr_return_quantity       as return_quantity,
    wr_return_amt            as return_amt,
    wr_return_tax            as return_tax,
    wr_net_loss              as net_loss
from {{ ref('fact_web_returns') }}
