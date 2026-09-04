"use client";

/**
 * The contract, worked out from the merchant's own rows.
 *
 * This is the answer to a question the screen used to beg. Every leak finding
 * says a row was charged above contract — and until now nothing on the page
 * said what the contract was, or where that figure came from. It came from
 * Razorpay's published pricing, which is right for a generated month and
 * wrong for anybody on a negotiated rate.
 *
 * So the rate is read off the rows instead, and shown here with the count it
 * was read from. **The count is the interesting column**, not the rate. A band
 * reading `2.000%` on `107 of 154` rows is telling a merchant two things at
 * once: this is your contract, and forty-seven of your card payments were not
 * charged at it.
 *
 * A band the rows would not settle is a question rather than a finding, and is
 * marked as one. Guessing the more popular of two rates would put a number
 * here that governs every leak claim on the page beneath it.
 */

import type { RateFinding, RatesView } from "@/lib/api";
import { Explain } from "./Explain";

function Row({ finding }: { finding: RateFinding }) {
  const settled = finding.rate !== null;

  return (
    <div className="grid grid-cols-[1fr_auto_auto] items-baseline gap-x-3 gap-y-0.5 py-1.5">
      <div className="text-[12.5px] font-medium">{finding.name}</div>
      <div
        className="text-[13px] font-medium tabular-nums"
        style={{ color: settled ? "var(--text)" : "var(--warn)" }}
      >
        {finding.rate ?? "unsettled"}
      </div>
      <div className="text-[11.5px] tabular-nums text-[var(--text-subtle)]">
        {finding.rows} of {finding.of}
      </div>
      <div className="col-span-3 text-[11.5px] leading-snug text-[var(--text-subtle)]">
        {finding.because}
        {settled && finding.disagreeing > 0 && (
          <>
            {" "}
            <span style={{ color: "var(--warn)" }}>
              {finding.disagreeing} row{finding.disagreeing === 1 ? "" : "s"} were not.
            </span>
          </>
        )}
      </div>
    </div>
  );
}

export function Rates({ rates }: { rates: RatesView }) {
  if (rates.findings.length === 0) return null;

  return (
    <section className="card px-5 py-4">
      <div className="text-[12px] font-medium text-[var(--text-muted)]">
        What you are charged, read from your own rows
      </div>

      <div className="mt-2 divide-y divide-[var(--border)]">
        {rates.findings.map((finding) => (
          <Row key={finding.name} finding={finding} />
        ))}
      </div>

      <div className="mt-3">
        <Explain question="Where does this come from?">
          <p>
            Your settlement report states the method and card type of every payment, and those
            are the two things Razorpay&apos;s pricing actually varies on. So for each kind of
            row we ask what rows like it were charged, take the rate that most of them agree on,
            and keep it only if it reproduces every one of those fees to the paisa.
          </p>
          <p>
            The count beside each rate is the part worth reading. If a band says{" "}
            <em>2.000% on 107 of 154 rows</em>, the other forty-seven were charged something
            else — which is exactly what the overcharge findings elsewhere on this page are
            about.
          </p>
          <p>
            This rests on one stated assumption: that being overcharged is the minority case. A
            band whose rows split evenly between two rates has not told us which one is your
            contract, so it is shown as unsettled rather than resolved to the more popular half.
            Nothing here replaces a rate you have told us.
          </p>
        </Explain>
      </div>
    </section>
  );
}
