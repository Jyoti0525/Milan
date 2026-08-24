# The Money Rules (Real Indian Numbers)

All of this is from Razorpay's official pricing and docs, not from memory.
Sources are at the bottom. Our engine must model every line here.

## The fee stack

| Component | Actual value |
|---|---|
| Platform fee — cards, UPI, netbanking, wallets, PayLater, EMI | **2%** |
| Corporate / business cards | **2.15%** |
| International cards | **up to 3%** |
| **GST on platform fee** | **18%** |
| **TDS under Section 194-O** | **1% on gross — NOT on the GST component** |
| Setup fee / AMC / refund processing | **Rs 0** |
| Instant refund | Rs 7.99 (<=1k) / Rs 11.99 (1k-25k) / Rs 14.99 (>25k) |
| Route | 0.1% + platform fee |
| Smart Collect | 1% or Rs 10, whichever is **lower** |
| QR — UPI / Bharat QR cards | 0.99% / 2.0% |

## Settlement timing

- **Domestic:** T+2 working days (T = the day the payment was captured)
- **International:** T+7 working days
- **Instant settlement:** available on request, minutes instead of days

## Worked example (Razorpay's own)

A Rs 10,000 card transaction:

```
Gross                Rs 10,000
- Platform fee 2%    Rs    200
- GST on fee 18%     Rs     36
= Net settled        Rs  9,764
```

## The four facts that make this genuinely hard

These are confirmed real, and all four go into our data generator:

**1. Refunds come out of FUTURE settlement batches.**
They are not paid as a separate debit. A refund lands 5-7 working days after it
was started, netted into whichever batch happens to be running then. So a refund
hits a batch that has nothing to do with the original sale.

**2. Sub-rupee rounding creates real exceptions.**
Fees are rounded per transaction; taxes are rounded on the batch. The two
roundings disagree by paise. This is a named, recognised exception category.

**3. Fee rates vary by instrument, and contracted rates may not match charged rates.**
A merchant may be on 2% but get charged 2.15% on corporate cards.

**4. GST on fees must reconcile against a MONTHLY tax invoice.**
GST-registered merchants claim Input Tax Credit (ITC) on the GST charged on
fees. To do that, the GST in the settlement file must match Razorpay's monthly
tax invoice. This is a second, separate matching problem.

## Real report field names

Our synthetic data uses Razorpay's actual field names, not invented ones:

```
entity_id       type          debit          credit
amount          currency      fee            tax
on_hold         settled       created_at     settled_at
settlement_id   settlement_utr
order_id        order_receipt payment_id
method          card_network  card_issuer    card_type
dispute_id
```

`settlement_utr` is the key that links a Razorpay settlement to a bank credit.

## Exception categories (industry standard names)

We use the names the industry already uses:

| Code | Meaning |
|---|---|
| `FEE_DEDUCTION` | Fee rate difference |
| `TAX_DEDUCTION` | GST variance against the invoice |
| `ROUNDING` | Acceptable sub-rupee difference |
| `PARTIAL_PAYMENT` | Refund-driven variance |
| `UNEXPLAINED` | In the bank credit but missing from the order system |

## Sources

- Razorpay Pricing — https://razorpay.com/pricing/
- Razorpay Settlements Docs — https://razorpay.com/docs/payments/settlements/
- Section 194-O guide (RazorpayX) — https://razorpay.com/learn/section-194o-tds-for-e-commerce-businesses/
- Settlement reconciliation breakdown — https://www.terra-insight.com/insights/razorpay-settlement-reconciliation/
- Settlement API fields — https://github.com/razorpay/razorpay-java/blob/master/documents/settlement.md
