"""Silver layer column types. Everything defaults to text; this module
enumerates the columns that should be cast to date / integer / numeric.

Design: explicit per-(table,column) overrides for dates and money, plus
a simple rule for _sk -> integer. Everything else stays TEXT so Silver
preserves Bronze strings (trimmed, empty->NULL) for descriptive columns.
"""
from __future__ import annotations

# -- Explicit non-TEXT columns --------------------------------------------
# Keys are (table, column); values are Postgres types.

DATES: set[tuple[str, str]] = {
    ("date_dim", "d_date"),
    ("item", "i_rec_start_date"), ("item", "i_rec_end_date"),
    ("store", "s_rec_start_date"), ("store", "s_rec_end_date"),
    ("call_center", "cc_rec_start_date"), ("call_center", "cc_rec_end_date"),
    ("web_page", "wp_rec_start_date"), ("web_page", "wp_rec_end_date"),
    ("web_site", "web_rec_start_date"), ("web_site", "web_rec_end_date"),
    ("dbgen_version", "dv_create_date"),
}

# Integer columns that don't match the _sk rule.
INTEGERS: set[tuple[str, str]] = {
    # date_dim non-sk ints
    ("date_dim", "d_month_seq"), ("date_dim", "d_week_seq"),
    ("date_dim", "d_quarter_seq"), ("date_dim", "d_year"),
    ("date_dim", "d_dow"), ("date_dim", "d_moy"),
    ("date_dim", "d_dom"), ("date_dim", "d_qoy"),
    ("date_dim", "d_fy_year"), ("date_dim", "d_fy_quarter_seq"),
    ("date_dim", "d_fy_week_seq"), ("date_dim", "d_first_dom"),
    ("date_dim", "d_last_dom"), ("date_dim", "d_same_day_ly"),
    ("date_dim", "d_same_day_lq"),
    # time_dim
    ("time_dim", "t_time"), ("time_dim", "t_hour"),
    ("time_dim", "t_minute"), ("time_dim", "t_second"),
    # customer
    ("customer", "c_birth_day"), ("customer", "c_birth_month"),
    ("customer", "c_birth_year"),
    # customer_demographics
    ("customer_demographics", "cd_purchase_estimate"),
    ("customer_demographics", "cd_dep_count"),
    ("customer_demographics", "cd_dep_employed_count"),
    ("customer_demographics", "cd_dep_college_count"),
    # household_demographics
    ("household_demographics", "hd_dep_count"),
    ("household_demographics", "hd_vehicle_count"),
    # income_band
    ("income_band", "ib_lower_bound"), ("income_band", "ib_upper_bound"),
    # item
    ("item", "i_brand_id"), ("item", "i_class_id"),
    ("item", "i_category_id"), ("item", "i_manufact_id"),
    ("item", "i_manager_id"),
    # promotion
    ("promotion", "p_response_target"),
    # store
    ("store", "s_number_employees"), ("store", "s_floor_space"),
    ("store", "s_market_id"), ("store", "s_division_id"),
    ("store", "s_company_id"),
    # call_center
    ("call_center", "cc_employees"), ("call_center", "cc_sq_ft"),
    ("call_center", "cc_mkt_id"), ("call_center", "cc_division"),
    ("call_center", "cc_company"),
    # catalog_page
    ("catalog_page", "cp_catalog_number"),
    ("catalog_page", "cp_catalog_page_number"),
    # warehouse
    ("warehouse", "w_warehouse_sq_ft"),
    # web_page
    ("web_page", "wp_char_count"), ("web_page", "wp_link_count"),
    ("web_page", "wp_image_count"), ("web_page", "wp_max_ad_count"),
    # web_site
    ("web_site", "web_mkt_id"), ("web_site", "web_company_id"),
    # facts: quantity + order number
    ("store_sales", "ss_quantity"), ("store_sales", "ss_ticket_number"),
    ("store_returns", "sr_return_quantity"), ("store_returns", "sr_ticket_number"),
    ("catalog_sales", "cs_quantity"), ("catalog_sales", "cs_order_number"),
    ("catalog_returns", "cr_return_quantity"), ("catalog_returns", "cr_order_number"),
    ("web_sales", "ws_quantity"), ("web_sales", "ws_order_number"),
    ("web_returns", "wr_return_quantity"), ("web_returns", "wr_order_number"),
    ("inventory", "inv_quantity_on_hand"),
}

# Numeric(7,2) columns (money, percentages, GMT offsets).
_NUMERIC_SUFFIXES = (
    "_price", "_cost", "_amt", "_amount", "_tax", "_paid", "_profit",
    "_loss", "_fee", "_cash", "_charge", "_credit",
    "_gmt_offset", "_tax_percentage", "_tax_precentage",
)


def is_numeric_col(column: str) -> bool:
    return column.endswith(_NUMERIC_SUFFIXES)


def silver_type(table: str, column: str) -> str:
    """Return the target Postgres type for a column when cast to Silver."""
    if (table, column) in DATES:
        return "date"
    if column.endswith("_sk"):
        return "integer"
    if (table, column) in INTEGERS:
        return "integer"
    if is_numeric_col(column):
        return "numeric(7,2)"
    return "text"


# Convention for naming Silver models.
_DIMENSIONS = {
    "call_center", "catalog_page", "customer", "customer_address",
    "customer_demographics", "date_dim", "household_demographics",
    "income_band", "item", "promotion", "reason", "ship_mode", "store",
    "time_dim", "warehouse", "web_page", "web_site",
}
_FACTS = {
    "catalog_returns", "catalog_sales", "inventory",
    "store_returns", "store_sales", "web_returns", "web_sales",
}


def silver_model_name(table: str) -> str:
    if table in _DIMENSIONS:
        return f"dim_{table}"
    if table in _FACTS:
        return f"fact_{table}"
    return table  # e.g. dbgen_version -> no prefix (we'll skip it)


def silver_tables() -> list[str]:
    """Bronze tables that should produce Silver models (excludes metadata)."""
    return sorted(_DIMENSIONS | _FACTS)
