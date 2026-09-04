"""The questions this can answer, and how a typed sentence reaches one.

A fixed vocabulary on purpose. An open-ended settlement assistant has to
either answer everything - which means answering things it cannot compute -
or refuse in a way the person cannot predict. A closed list can be measured:
either a question reaches the right one of these or it does not, and the
share that arrive with no model involved is a number rather than a claim.

`triggers` are read as: every group must find one of its words somewhere in
the question. So `({"short", "less"}, {"payout", "settlement"})` matches "why
was my settlement less" and does not match "what was settled". Words, not
regular expressions, because merchants type "shortfall", "short by", "short-
fall" and "came up short", and a pattern precise enough to distinguish those
is precise enough to miss all four.

Order is load-bearing here exactly as it is in the categoriser: the first
intent whose triggers are satisfied wins, so the specific questions sit above
the general ones. `overcharge` precedes `charges` because "am I being charged
too much" is a question about the contract and "what was I charged" is a
question about the total, and the words overlap almost entirely.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict

Trigger = tuple[frozenset[str], ...]


class Intent(BaseModel):
    """One question this package knows how to compute an answer to."""

    model_config = ConfigDict(frozen=True)

    name: str
    asks: str
    """What this question means, in the words a model is shown when the
    rules cannot route. Written for a reader rather than as a label, because
    a one-word category is not enough for anything to choose between ten of
    them."""

    example: str
    """A phrasing a merchant would actually type. Shown on a refusal, so the
    reply to "I do not understand" is a list of things that do work."""

    triggers: tuple[Trigger, ...] = ()
    """Any one of these satisfied routes the question here, with no model."""


def _t(*groups: set[str]) -> Trigger:
    return tuple(frozenset(group) for group in groups)


WHY = {"why", "how", "what", "which", "explain", "cause", "reason", "wrong"}
MUCH = {"much", "many", "total", "sum", "amount", "worth"}


CATALOGUE: tuple[Intent, ...] = (
    Intent(
        name="proof",
        asks="Break one bank credit or one settlement down into the rows behind it.",
        example="show me bank_3m6ts349i2nzvt",
        # No triggers. This one is reached by finding an id in the question,
        # which is a stronger signal than any word could be - see `subject_in`.
    ),
    Intent(
        name="overcharge",
        asks=(
            "Money lost to fees charged above the rate this merchant is "
            "contracted to, on payouts that otherwise reconciled perfectly."
        ),
        example="am I being overcharged?",
        triggers=(
            _t({"overcharged", "overcharge", "overcharging", "overcharges"}),
            _t({"leak", "leaks", "leaking", "leakage"}),
            # Doubting a rate is not the same question as totalling it. "Are
            # you sure the MDR is 2%" reached `charges` and came back with a
            # month's fee total, which answers a question about arithmetic
            # with arithmetic and leaves the question about the contract
            # untouched.
            _t(
                {"sure", "correct", "right", "supposed", "meant", "should"},
                {"rate", "rates", "mdr", "pricing", "fee", "fees", "percent", "commission"},
            ),
            # Two halves: something that means *comparing or exceeding*, and
            # something that means *the agreed price*. Neither half routes on
            # its own, which is what keeps "what are my transaction charges"
            # out of here - that names the price without questioning it.
            _t(
                {
                    "wrong",
                    "higher",
                    "above",
                    "more",
                    "losing",
                    "lose",
                    "lost",
                    "check",
                    "compare",
                    "verify",
                    "against",
                    "audit",
                    "review",
                },
                {
                    "rate",
                    "rates",
                    "contract",
                    "contracted",
                    "agreed",
                    "agreement",
                    "pricing",
                    "signed",
                    "quoted",
                    "promised",
                },
            ),
        ),
    ),
    Intent(
        name="shortfall",
        asks=(
            "Why payouts arrived smaller than the settlement report says they "
            "should have, and what the difference was."
        ),
        example="why was my payout short?",
        triggers=(
            _t({"short", "shortfall", "shortfalls", "shorter", "less", "lower", "smaller"}),
            # A deduction is only this question when the sentence says it was
            # *unwarranted*. Paired with a size word instead, it caught "sum
            # of every deduction the gateway took" - a plain request for a
            # total, answered as a complaint about money missing. That one
            # belongs to `charges`, which is where it now lands.
            _t(
                {"deducted", "deduction", "deductions"},
                {
                    "shouldnt",
                    "shouldn't",
                    "wrongly",
                    "wrong",
                    "extra",
                    "unexpected",
                    "why",
                    "unexplained",
                },
            ),
            # A word meaning "these two do not agree", tied to one of the two
            # things that are supposed to. Both halves are required, and the
            # second half is deliberately a list of settlement nouns rather
            # than anything general: "the discrepancy between these two files"
            # names no side of the identity and stays unrouted, because which
            # two files somebody means is not something this can know.
            _t(
                {"gap", "difference", "differs", "discrepancy", "mismatch", "variance"},
                {
                    "report",
                    "deposit",
                    "deposits",
                    "payout",
                    "payouts",
                    "settlement",
                    "bank",
                    "credit",
                    "credited",
                    "advice",
                    "amount",
                },
            ),
        ),
    ),
    Intent(
        name="unsettled",
        asks=(
            "Payments the merchant captured that the settlement report never "
            "mentions at all - money that left the customer and was never "
            "claimed to have been paid on."
        ),
        example="what hasn't been settled yet?",
        triggers=(
            _t({"unsettled", "settled"}, {"not", "never", "yet", "hasnt", "hasn't", "havent"}),
            _t({"captured", "capture"}, {"missing", "never", "not"}),
            _t({"owe", "owed", "owes", "outstanding", "pending"}),
            # "Due" needs a second word, unlike the rest of that group. On its
            # own it swings between two questions - "everything still due to
            # me" is this one, "when is my payout due" is `timing` - and the
            # words that disambiguate it are the ones that say *to whom*.
            _t({"due"}, {"me", "us", "still", "money", "payment", "payments"}),
            _t({"stuck", "unpaid"}),
        ),
    ),
    Intent(
        name="landing",
        asks=(
            "When money the merchant has already captured is due to reach "
            "the bank, day by day - the published settlement cycle applied "
            "to their own captures, not a prediction about future sales."
        ),
        example="when is my money landing?",
        triggers=(
            # Deliberately narrow, and deliberately about money that already
            # exists. Every trigger here needs a word naming a payout beside
            # a word about arrival, so "when do payouts land" reaches this
            # and "what will I make next month" reaches nothing - which is
            # correct, because nothing in these files knows.
            _t(
                {"when", "coming", "incoming", "upcoming", "expect", "expected", "expecting"},
                {
                    "land",
                    "lands",
                    "landing",
                    "arrive",
                    "arrives",
                    "arriving",
                    "settle",
                    "settles",
                    "payout",
                    "payouts",
                    "money",
                    "cash",
                    "paid",
                    "credited",
                    "deposit",
                    "deposits",
                    "in",
                },
            ),
            _t({"still"}, {"come", "coming", "arrive", "land"}),
            _t({"pipeline", "in-flight", "inflight"}),
            # "Due" alone belongs to `unsettled`, which sits above this and
            # keeps it. Paired with a word about arriving it is this question
            # instead, and it has to be here rather than left to the date
            # fallback: "how much is due to land by Friday" carries a date,
            # and a date nothing claims is answered as "what happened that
            # day" - a question about the past, put by somebody asking about
            # the future.
            _t(
                {"due"},
                {"land", "lands", "landing", "arrive", "arrives", "reach", "come", "coming"},
            ),
        ),
    ),
    Intent(
        name="largest",
        asks="The biggest payouts of the period, for cash planning rather than triage.",
        example="what were my biggest payouts?",
        triggers=(
            _t(
                {"biggest", "largest", "top", "highest"},
                {
                    "payout",
                    "payouts",
                    "credit",
                    "credits",
                    "deposit",
                    "deposits",
                    "settlement",
                    "settlements",
                },
            ),
        ),
    ),
    Intent(
        name="by_method",
        asks=(
            "What each payment method brought in and what it cost to accept - "
            "UPI, cards, netbanking, wallets, EMI, pay later."
        ),
        example="how much came in on UPI?",
        triggers=(
            _t({"upi", "card", "cards", "netbanking", "wallet", "wallets", "emi", "paylater"}),
            _t({"method", "methods", "instrument", "instruments", "mode", "modes"}),
        ),
    ),
    Intent(
        name="timing",
        asks=(
            "How long money actually takes to reach the bank on these rows, "
            "rather than the published T+2."
        ),
        example="how long do payouts take?",
        triggers=(
            _t(
                {
                    "long",
                    "lag",
                    "delay",
                    "delayed",
                    "slow",
                    "slower",
                    "quick",
                    "quicker",
                    "quickly",
                    "faster",
                    "sooner",
                    "soon",
                    "late",
                    "cycle",
                },
                {
                    "settle",
                    "settles",
                    "settled",
                    "settlement",
                    "payout",
                    "payouts",
                    "paid",
                    "pay",
                    "take",
                    "takes",
                },
            ),
        ),
    ),
    Intent(
        name="on_a_day",
        asks="Everything that happened on one named date - money in, payouts, captures, cases.",
        example="what happened on 14 July?",
        triggers=(_t({"happened", "happen", "happening"}),),
    ),
    Intent(
        name="biggest",
        asks="The single largest thing wrong with this month, and what to do about it.",
        example="what's the biggest problem here?",
        triggers=(
            _t(
                {
                    "biggest",
                    "largest",
                    "worst",
                    "priority",
                    "first",
                    "urgent",
                    "urgently",
                    "attention",
                    "pressing",
                    "important",
                }
            ),
            # "should" plus "I" was here and had to go. It caught "should I
            # switch payment gateway" and "what will my sales be next month",
            # neither of which this can compute, and answering them with the
            # month's largest cause is the exact failure the whole package is
            # arranged to prevent. A verb that means prioritising is required
            # instead, and the phrasings that no longer route are a real cost
            # paid on purpose - the model is there for those.
            _t(
                {"should", "shall"},
                {"chase", "fix", "tackle", "focus", "prioritise", "prioritize"},
            ),
        ),
    ),
    Intent(
        name="unexplained",
        asks=(
            "What could not be reconciled, grouped into the few reasons behind "
            "it rather than listed one row at a time."
        ),
        example="what can't you explain?",
        triggers=(
            _t({"unexplained", "unresolved", "unmatched", "exceptions", "exception"}),
            _t(
                {"cannot", "cant", "can't", "could", "couldnt", "couldn't", "unable"},
                {"match", "matched", "explain", "explained", "reconcile", "reconciled"},
            ),
            _t(WHY, {"problems", "problem", "issues", "issue", "queue"}),
            # "Open" carries the sense only next to the thing that is open.
            # Alone it is a verb - "open the queue" - and the noun is what
            # says this is a question about what remains unresolved.
            _t({"open", "unclosed"}, {"items", "item", "cases", "case", "queue", "list"}),
        ),
    ),
    # Above `charges`, and that order is the whole point. Both questions are
    # about money the merchant did not keep, and `charges` owns the word
    # "cost" - so "how much did returns cost me" was answered with the
    # gateway's fees, which is a real figure about the wrong money. A
    # sentence that names a refund is a question about refunds whatever verb
    # it uses; a sentence about fees never names one.
    Intent(
        name="refunds",
        asks="Refunds and chargebacks over the period, and what they cost.",
        example="how much went back in refunds?",
        triggers=(
            _t({"refund", "refunds", "refunded", "returns", "returned"}),
            _t({"chargeback", "chargebacks", "dispute", "disputes"}),
        ),
    ),
    Intent(
        name="charges",
        asks=(
            "What the gateway charged over the period - the platform fee, the "
            "GST on it, and any statutory withholding."
        ),
        example="how much did I pay in fees?",
        triggers=(
            _t({"fee", "fees", "commission", "mdr", "charge", "charged", "charges", "cost"}),
            _t({"gst"}),
            # The neutral total, handed down from `shortfall`, which now only
            # takes a deduction the sentence calls unwarranted.
            _t({"deduction", "deductions", "deducted"}, MUCH),
            # Withholding split off with a size word attached, and the
            # `merchant` intent takes it without one. "How much TDS came off"
            # wants the figure; "is TDS being deducted" wants to know whether
            # this merchant is an operator at all, and answering the second
            # with a total is answering a question nobody asked.
            _t({"tds", "withheld", "withholding", "194", "194-o"}, MUCH),
        ),
    ),
    Intent(
        name="merchant",
        asks=(
            "What these files say about who this merchant is - whether 1% is "
            "withheld under Section 194-O, whether sales are split onward "
            "through Route, whether payouts are taken the same day."
        ),
        example="is TDS being deducted from my payouts?",
        triggers=(
            _t({"194", "194-o", "operator", "ecommerce", "e-commerce"}),
            _t({"tds", "withheld", "withholding"}),
            _t({"route", "linked", "marketplace"}),
            # "Split" needs to say what it is split *to*. On its own it took
            # "revenue split across payment modes", which is a breakdown
            # question, and answered it with a paragraph about Route.
            _t(
                {"split", "splits", "onward"},
                {"route", "linked", "account", "accounts", "sub", "sellers", "vendors", "partners"},
            ),
            _t({"instant"}, {"settlement", "settlements", "payout", "payouts"}),
        ),
    ),
    Intent(
        name="received",
        asks="What actually arrived in the bank over the period, and on which days.",
        example="how much did I actually receive?",
        triggers=(
            # A receiving verb, not a bare noun. "Deposit" alone was a trigger
            # here and it caught "there is a gap between the report and the
            # deposit", which is a shortfall question answered with a total -
            # a confident reply about something nobody asked. A question needs
            # to say that money *arrived*, not merely mention a deposit.
            _t({"received", "receive", "arrived", "arrive", "credited", "hit"}),
            # "Bank" and "account" used to sit in here beside a size word,
            # which made "the amount in my account is not what the panel
            # showed" a question about how much arrived. It is the opposite -
            # a complaint that two figures disagree - and it was answered
            # with a confident total. Naming where the money lives is not the
            # same as saying it got there, so the group is now only words
            # that mean it did.
            _t(MUCH, {"deposits", "deposited", "credited", "inflow"}),
            # The same rule as above, kept: a deposit is only this question
            # when the sentence says it *landed*. The bare noun stays with
            # `shortfall`, where "a gap between the report and the deposit"
            # belongs.
            _t(
                {"deposit", "deposits", "money", "payout", "payouts"},
                {"came", "come", "coming", "landed", "in"},
            ),
            # "Paid out to me" is receiving, and it reaches here rather than
            # `timing` only because `timing` needs a word about speed. Both
            # readings of "paid" are live, and the order settles it.
            _t(MUCH, {"paid"}),
        ),
    ),
)

BY_NAME: dict[str, Intent] = {intent.name: intent for intent in CATALOGUE}


def examples() -> tuple[str, ...]:
    """What to show somebody whose question did not reach anything.

    `proof` is left out: its example contains a record id from one particular
    month, and suggesting an id that does not exist in the month being looked
    at is worse than suggesting nothing.
    """
    return tuple(intent.example for intent in CATALOGUE if intent.name != "proof")
