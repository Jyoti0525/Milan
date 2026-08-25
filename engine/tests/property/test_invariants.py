"""Financial invariants, checked against inputs nobody chose.

Example-based tests check the cases we thought of. These check the ones we
did not, which is the entire reason they are worth the dependency: every
rounding bug in this project would have passed a hand-written test, because a
hand-written test uses amounts a person would think to type.

Each property below is a statement about money that must hold for every
input, not a statement about how the code currently behaves. A test that
merely re-describes the implementation passes forever and catches nothing.
"""

from __future__ import annotations

from decimal import Decimal

from hypothesis import assume, given, settings
from hypothesis import strategies as st

from milan.domain.enums import CardType, EntityType, PaymentMethod
from milan.domain.money import Paise, apply_rate, format_inr, from_rupees
from milan.domain.rates import RateCard, compute_deductions
from milan.domain.records import SettlementRow
from milan.recon.batches import BatchGroup, rebuild_batches
from milan.recon.matching.exact import extract_utr

# Real order values, from a hundred rupees to five lakh.
amounts = st.integers(min_value=100_00, max_value=5_00_000_00).map(Paise)
methods = st.sampled_from(list(PaymentMethod))
card_types = st.sampled_from([None, *CardType])
rates = st.builds(RateCard, tds_applies=st.booleans())


class TestMoneyArithmetic:
    @given(rupees=st.decimals(min_value=0, max_value=10_000_000, places=2))
    def test_rupees_to_paise_never_loses_a_paisa(self, rupees: Decimal) -> None:
        """The conversion is exact, so it must be reversible.

        Paise are integers precisely so that no amount is ever approximate.
        If this can drift, every figure in the system is a rounding of a
        rounding.
        """
        assert Decimal(from_rupees(rupees)) == (rupees * 100).to_integral_value()

    @given(base=amounts, rate=st.decimals(min_value=0, max_value=1, places=4))
    def test_a_rate_never_produces_more_than_the_base(self, base: Paise, rate: Decimal) -> None:
        """A percentage of an amount cannot exceed it. Obvious, and exactly
        the kind of thing a sign error breaks silently."""
        assert 0 <= apply_rate(base, rate) <= base

    @given(base=amounts, rate=st.decimals(min_value=0, max_value=1, places=4))
    def test_rounding_is_never_more_than_half_a_paisa_out(self, base: Paise, rate: Decimal) -> None:
        """The rounding allowance elsewhere is derived from this bound.

        If a single rounding could be a whole paisa out, the batch allowance
        would be too tight and honest drift would be raised as an exception.
        """
        exact = Decimal(base) * rate
        assert abs(Decimal(apply_rate(base, rate)) - exact) <= Decimal("0.5")

    @given(paise=st.integers(min_value=-(10**12), max_value=10**12).map(Paise))
    def test_formatting_always_shows_two_decimal_places(self, paise: Paise) -> None:
        """A finance figure with one decimal place is a typo to a reader."""
        rendered = format_inr(paise)
        assert rendered.count(".") == 1
        assert len(rendered.split(".")[1]) == 2


class TestTheFeeStack:
    @given(gross=amounts, method=methods, card=card_types, card_rates=rates)
    def test_the_waterfall_always_closes(
        self, gross: Paise, method: PaymentMethod, card: CardType | None, card_rates: RateCard
    ) -> None:
        """gross - fee - tax - tds == net, for every input.

        This identity is asserted inside `Deductions`, so what this really
        checks is that no combination of method, card type and rate card can
        construct one that violates it.
        """
        result = compute_deductions(gross, method, card, card_rates)
        assert result.gross - result.fee - result.tax - result.tds == result.net

    @given(gross=amounts, method=methods, card=card_types, card_rates=rates)
    def test_a_merchant_is_never_charged_more_than_they_sold(
        self, gross: Paise, method: PaymentMethod, card: CardType | None, card_rates: RateCard
    ) -> None:
        """A settlement that pays out less than nothing is not a settlement."""
        result = compute_deductions(gross, method, card, card_rates)
        assert 0 <= result.total_deducted <= result.gross
        assert result.net >= 0

    @given(gross=amounts, method=methods, card=card_types)
    def test_gst_is_charged_on_the_fee_and_never_on_the_sale(
        self, gross: Paise, method: PaymentMethod, card: CardType | None
    ) -> None:
        """18% of the fee, not 18% of the transaction.

        Getting this wrong overstates GST by roughly fifty times and would
        still produce a report that foots.
        """
        card_rates = RateCard()
        result = compute_deductions(gross, method, card, card_rates)
        assert result.tax == apply_rate(result.fee, card_rates.gst)

    @given(gross=amounts, method=methods, card=card_types)
    def test_tds_is_charged_on_gross_and_never_on_the_gst(
        self, gross: Paise, method: PaymentMethod, card: CardType | None
    ) -> None:
        """Section 194-O withholds 1% of the sale, excluding the GST
        component. Charging it on gross-plus-GST is the common error."""
        card_rates = RateCard(tds_applies=True)
        result = compute_deductions(gross, method, card, card_rates)
        assert result.tds == apply_rate(gross, card_rates.tds)


def _row(entity_id: str, amount: Paise, settlement: str) -> SettlementRow:
    from datetime import datetime

    deductions = compute_deductions(amount, PaymentMethod.UPI, None, RateCard())
    return SettlementRow(
        entity_id=entity_id,
        type=EntityType.PAYMENT,
        debit=Paise(0),
        credit=deductions.net,
        amount=amount,
        fee=deductions.fee,
        tax=deductions.tax,
        created_at=datetime(2026, 7, 1, 12, 0),
        settled_at=datetime(2026, 7, 3, 11, 0),
        settlement_id=settlement,
        settlement_utr="UTR000000001",
        payment_id=entity_id,
        method=PaymentMethod.UPI,
    )


class TestBatchArithmetic:
    @given(values=st.lists(amounts, min_size=1, max_size=25))
    @settings(max_examples=50)
    def test_a_batch_nets_to_the_sum_of_its_rows(self, values: list[Paise]) -> None:
        rows = tuple(_row(f"pay_{i}", value, "setl_1") for i, value in enumerate(values))
        batch = rebuild_batches(rows)[0]
        assert batch.expected_net == sum(row.signed_net for row in rows)
        assert batch.gross == sum(values)

    @given(
        left=st.lists(amounts, min_size=1, max_size=12),
        right=st.lists(amounts, min_size=1, max_size=12),
    )
    @settings(max_examples=50)
    def test_a_group_totals_its_members_and_nothing_else(
        self, left: list[Paise], right: list[Paise]
    ) -> None:
        """Merging two settlements must not create or destroy money."""
        rows = tuple(
            [_row(f"a{i}", v, "setl_a") for i, v in enumerate(left)]
            + [_row(f"b{i}", v, "setl_b") for i, v in enumerate(right)]
        )
        batches = rebuild_batches(rows)
        group = BatchGroup.of(*batches)
        assert group.expected_net == sum(b.expected_net for b in batches)
        assert group.gross == sum(left) + sum(right)

    @given(
        left=st.lists(amounts, min_size=1, max_size=12),
        right=st.lists(amounts, min_size=1, max_size=12),
    )
    @settings(max_examples=50)
    def test_a_groups_allowance_is_wider_than_any_members(
        self, left: list[Paise], right: list[Paise]
    ) -> None:
        """Each settlement rounds its own GST once, so a group of two carries
        two roundings. An allowance that did not grow would turn honest drift
        into an exception on exactly the credits that are hardest to check."""
        rows = tuple(
            [_row(f"a{i}", v, "setl_a") for i, v in enumerate(left)]
            + [_row(f"b{i}", v, "setl_b") for i, v in enumerate(right)]
        )
        batches = rebuild_batches(rows)
        group = BatchGroup.of(*batches)
        assert group.rounding_allowance >= max(b.rounding_allowance for b in batches)


class TestReferenceExtraction:
    @given(
        reference=st.text(alphabet="ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", min_size=12, max_size=18)
    )
    def test_a_reference_surrounded_by_noise_is_still_found(self, reference: str) -> None:
        assume(any(character.isdigit() for character in reference))
        found = extract_utr(f"NEFT-{reference}-RAZORPAY SOFTWARE PVT LTD")
        assert found == reference

    @given(words=st.lists(st.sampled_from(["RAZORPAY", "SETTLEMENT", "INWARD", "NEFT", "IMPS"])))
    def test_narration_words_are_never_mistaken_for_a_reference(self, words: list[str]) -> None:
        """Inventing a reference is worse than admitting there is none: it
        turns a credit that would have gone to the amount rungs into a
        confident lookup against a settlement that does not exist."""
        assert extract_utr(" ".join(words)) is None
