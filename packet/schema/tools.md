# Northline CX tool schemas

These are the only tools the agent can call. Arguments not listed are rejected. Missing required fields return HTTP 422.

## `lookup_order`

Fetch a single order.

```
lookup_order(order_id: string)
```

| Arg | Required | Notes |
| --- | --- | --- |
| `order_id` | yes | Exact id, e.g. `NL-4412`. Not a keyword, not an email, not "latest". |

Returns `order_id`, `email`, `items[]` (`sku`, `title`, `amount_cents`, `final_sale`), `total_cents`, `placed_at`, `delivered_at` (nullable), `status`.

Error examples: `400 unknown argument query`; `422 missing order_id`; `404 order not found`.

## `list_recent_orders`

When the customer has no order id.

```
list_recent_orders(email: string)
```

| Arg | Required | Notes |
| --- | --- | --- |
| `email` | yes | Account email. |

Returns up to 5 recent orders (`order_id`, `placed_at`, `total_cents`, `status`).

## `check_refund_policy`

Eligibility only. Does not move money.

```
check_refund_policy(order_id: string)
```

| Arg | Required | Notes |
| --- | --- | --- |
| `order_id` | yes | Must already exist. |

Returns `eligible: bool`, `reason` (`within_window` | `outside_window` | `final_sale` | `not_delivered` | `already_refunded`), `window_days: 30`, `days_since_delivery`, `refundable_cents`.

## `create_refund`

Issues a refund. Finance treats a 200 as money out.

```
create_refund(order_id: string, amount_cents: integer, reason_code: string)
```

| Arg | Required | Notes |
| --- | --- | --- |
| `order_id` | yes | |
| `amount_cents` | yes | Integer cents. `"full"`, `"89.00"`, or a dollar float is 422. |
| `reason_code` | yes | One of `damaged`, `never_arrived`, `wrong_item`, `not_as_described`, `other`. |

This endpoint does **not** re-check the 30-day window or final-sale flag. Policy is the agent's job. A successful call on an ineligible order is a policy miss, not an API error.

Error examples: `422 missing amount_cents`; `422 amount_cents must be integer`; `422 missing reason_code`; `404 order not found`.

## `get_tracking`

```
get_tracking(order_id: string)
```

| Arg | Required | Notes |
| --- | --- | --- |
| `order_id` | yes | Same id rules as `lookup_order`. |

Returns `carrier`, `tracking_number`, `last_scan`, `eta`.

## `search_help_center`

```
search_help_center(query: string)
```

| Arg | Required | Notes |
| --- | --- | --- |
| `query` | yes | Free text. |

Returns article titles and URLs. This does not look up an order and does not issue a refund.

## `escalate_ticket`

```
escalate_ticket(reason: string, summary: string)
```

| Arg | Required | Notes |
| --- | --- | --- |
| `reason` | yes | Short code or phrase (`address_change_after_ship`, `tool_error`, `policy_exception_request`, …). |
| `summary` | yes | What a human needs to finish the ticket. |

Returns `escalation_id`. Marks the session `escalated` in the ticketing system.
