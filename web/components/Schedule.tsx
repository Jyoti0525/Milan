"use client";

/**
 * What is still coming, and the two things that are not.
 *
 * `Position` answers "what arrived". This answers "what has not yet", and the
 * pair is the whole cash position: money in the account, and money owed with
 * a date on it. Every date here is Razorpay's published settlement cycle
 * applied to a capture the merchant already made, and every amount is their
 * own fee stack applied to money they have already taken — so this is a
 * schedule rather than a forecast, and the sentence under the total says so
 * in those words rather than leaving it to be assumed.
 *
 * **The bars are the point.** A column of dates and rupees is a table; a
 * column of bars against the largest day is a shape, and the shape answers
 * the question a merchant actually has — which day carries the money — before
 * any figure has been read. The running total is beside each row for the same
 * reason: nobody asks what Thursday brings, they ask whether Friday's bill is
 * covered, and that is cumulative.
 *
 * **Three populations, never summed.** The headline is what is coming.
 * Overdue money has already failed to arrive; undated money has no date to
 * arrive on. Both are real and neither is cash flow, so they sit below a rule
 * in their own sentences — the same rule, for the same reason, as the one
 * `Position` draws above "never reached the bank at all".
 */

import type { Landing, ScheduleView } from "@/lib/api";
import { Amount } from "./Amount";
import { Explain } from "./Explain";

/** `2026-07-22` as `Wed 22 Jul`, without going near a timezone. */
function readable(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  const at = new Date(Date.UTC(year, month - 1, day));
  const weekday = at.toLocaleDateString("en-GB", { weekday: "short", timeZone: "UTC" });
  const name = at.toLocaleDateString("en-GB", { month: "short", timeZone: "UTC" });
  return `${weekday} ${String(day).padStart(2, "0")} ${name}`;
}

function Row({ landing, widest }: { landing: Landing; widest: number }) {
  /*
    Against the largest day rather than against the total, so a month with one
    big payout does not render every other day as an invisible sliver. The
    comparison a reader makes is between days.
  */
  const share = widest > 0 ? (landing.net / widest) * 100 : 0;

  return (
    <div className="grid grid-cols-[auto_1fr_auto] items-center gap-x-3 gap-y-1 py-1.5">
      <div className="text-[12px] tabular-nums text-[var(--text-muted)]">
        {readable(landing.on)}
      </div>
      <div className="meter h-[6px]">
        <span style={{ width: `${share}%`, background: "var(--accent-line)" }} />
      </div>
      <div className="text-right">
        <Amount paise={landing.net} size="md" />
      </div>
      <div />
      <div className="text-[11px] text-[var(--text-subtle)]">
        {landing.payments} payment{landing.payments === 1 ? "" : "s"}
      </div>
      <div className="text-right text-[11px] tabular-nums text-[var(--text-subtle)]">
        <Amount paise={landing.running} size="sm" /> by then
      </div>
    </div>
  );
}

export function Schedule({ schedule }: { schedule: ScheduleView }) {
  const { landings } = schedule;
  const widest = landings.reduce((most, landing) => Math.max(most, landing.net), 0);
  const last = landings.at(-1);

  return (
    <section className="card px-5 py-4">
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <div>
          <div className="text-[12px] font-medium text-[var(--text-muted)]">
            Captured, and still to reach your account
          </div>
          <div className="mt-0.5">
            <Amount paise={schedule.committed} size="xl" />
          </div>
        </div>
        <div className="text-[11.5px] text-[var(--text-subtle)]">
          {schedule.payments.toLocaleString("en-IN")} payments · as of{" "}
          {readable(schedule.as_of)}
        </div>
      </div>

      {landings.length > 0 ? (
        <>
          <div className="mt-3 divide-y divide-[var(--border)]">
            {landings.map((landing) => (
              <Row key={landing.on} landing={landing} widest={widest} />
            ))}
          </div>
          <div className="mt-2 text-[11.5px] text-[var(--text-subtle)]">
            Dated by the published settlement cycle — T+2 working days, T+7 on international
            cards — applied to your own capture times. Nothing here is predicted.
            {last ? ` All of it is due by ${readable(last.on)}.` : ""}
          </div>
        </>
      ) : (
        <div className="mt-3 text-[12.5px] text-[var(--text-muted)]">
          Every payment in these files has already been paid out. Nothing is in flight.
        </div>
      )}

      {(schedule.overdue_count > 0 || schedule.undated.length > 0) && (
        <div className="mt-3.5 space-y-2 border-t border-[var(--border)] pt-3">
          {schedule.overdue_count > 0 && (
            <div className="text-[12.5px] text-[var(--text-muted)]">
              Separately, <Amount paise={schedule.overdue_net} size="sm" /> across{" "}
              {schedule.overdue_count} payment{schedule.overdue_count === 1 ? "" : "s"} was due
              before {readable(schedule.as_of)} and has no payout behind it.
            </div>
          )}
          {schedule.undated.length > 0 && (
            <div className="text-[12.5px] text-[var(--text-muted)]">
              A further <Amount paise={schedule.undated_net} size="sm" /> across{" "}
              {schedule.undated.length} row{schedule.undated.length === 1 ? "" : "s"} has no date
              these files support — {schedule.undated[0].because}.
            </div>
          )}
        </div>
      )}

      <div className="mt-3">
        <Explain question="Is this a forecast?">
          <p>
            No, and the difference is the reason you can rely on it. A forecast says what is
            likely; this says what is owed and when it is due. Every rupee here is money a
            customer has already paid you and your gateway has not yet paid on.
          </p>
          <p>
            The dates are Razorpay&apos;s published settlement cycle applied to your own capture
            timestamps. The amounts are your own fee stack — platform fee, the GST on it, and any
            Section 194-O withholding — applied to amounts you have already taken. No sales are
            projected, and no trend is fitted.
          </p>
          <p>
            Three things move a real payout that this cannot see: an instant settlement you ask
            for, a Route split to a linked account, and a refund a customer has not requested
            yet. Refunds already raised are in the undated line above; the other two would arrive
            early or arrive smaller, and neither is invented here.
          </p>
        </Explain>
      </div>
    </section>
  );
}
