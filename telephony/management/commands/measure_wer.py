"""Measure Word Error Rate (WER) for the QWR voice bot transcription.

Usage:
    # Auto-fill hypotheses from the latest test call, then compute WER:
    python manage.py measure_wer --call-sid <SID>

    # Or compute WER from an already-filled test set file:
    python manage.py measure_wer --file tests/wer_test_set.json

    # List recent calls to pick one:
    python manage.py measure_wer --list-calls

WER formula:
    WER = (Substitutions + Insertions + Deletions) / Reference_word_count

The test set lives in tests/wer_test_set.json. Fill the "reference" fields
with ground truth (what was actually said) and either:
  - Provide "hypothesis" manually, OR
  - Use --call-sid to auto-fill from stored transcription.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from django.core.management.base import BaseCommand

from telephony.models import Call, TranscriptTurn


def _normalize(text: str) -> list[str]:
    """Lowercase, strip punctuation, split into words."""
    import re
    text = text.lower().strip()
    text = re.sub(r"[^\w\s]", "", text)  # remove punctuation
    return text.split()


def _edit_distance(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """Compute edit distance and return (substitutions, insertions, deletions)."""
    n = len(ref)
    m = len(hyp)

    # dp[i][j] = (cost, subs, ins, dels)
    dp = [[(0, 0, 0, 0) for _ in range(m + 1)] for _ in range(n + 1)]

    for i in range(1, n + 1):
        dp[i][0] = (i, 0, 0, i)  # all deletions
    for j in range(1, m + 1):
        dp[0][j] = (j, 0, j, 0)  # all insertions

    for i in range(1, n + 1):
        for j in range(1, m + 1):
            if ref[i - 1] == hyp[j - 1]:
                dp[i][j] = dp[i - 1][j - 1]
            else:
                # Substitution
                sub = dp[i - 1][j - 1]
                sub_cost = (sub[0] + 1, sub[1] + 1, sub[2], sub[3])

                # Deletion (ref word skipped)
                dl = dp[i - 1][j]
                del_cost = (dl[0] + 1, dl[1], dl[2], dl[3] + 1)

                # Insertion (extra word in hyp)
                ins = dp[i][j - 1]
                ins_cost = (ins[0] + 1, ins[1], ins[2] + 1, ins[3])

                dp[i][j] = min(sub_cost, del_cost, ins_cost, key=lambda x: x[0])

    _, subs, ins, dels = dp[n][m]
    return subs, ins, dels


def compute_wer(reference: str, hypothesis: str) -> dict:
    """Compute WER between a reference and hypothesis string."""
    ref_words = _normalize(reference)
    hyp_words = _normalize(hypothesis)

    if not ref_words:
        return {
            "wer": 0.0 if not hyp_words else 1.0,
            "substitutions": 0,
            "insertions": len(hyp_words),
            "deletions": 0,
            "ref_words": 0,
            "hyp_words": len(hyp_words),
        }

    subs, ins, dels = _edit_distance(ref_words, hyp_words)
    wer = (subs + ins + dels) / len(ref_words)

    return {
        "wer": round(wer, 4),
        "substitutions": subs,
        "insertions": ins,
        "deletions": dels,
        "ref_words": len(ref_words),
        "hyp_words": len(hyp_words),
    }


class Command(BaseCommand):
    help = "Measure Word Error Rate (WER) for voice bot transcription"

    def add_arguments(self, parser):
        parser.add_argument(
            "--file",
            type=str,
            default="tests/wer_test_set.json",
            help="Path to the WER test set JSON file",
        )
        parser.add_argument(
            "--call-sid",
            type=str,
            default=None,
            help="Auto-fill hypotheses from a specific call's transcripts",
        )
        parser.add_argument(
            "--call-id",
            type=int,
            default=None,
            help="Auto-fill hypotheses from a specific call by DB ID",
        )
        parser.add_argument(
            "--list-calls",
            action="store_true",
            help="List recent calls with transcripts",
        )
        parser.add_argument(
            "--save",
            action="store_true",
            help="Save the filled hypotheses back to the test set file",
        )

    def handle(self, *args, **options):
        if options["list_calls"]:
            self._list_calls()
            return

        test_file = Path(options["file"])
        if not test_file.exists():
            self.stderr.write(self.style.ERROR(f"Test set file not found: {test_file}"))
            sys.exit(1)

        with open(test_file) as f:
            test_data = json.load(f)

        utterances = test_data.get("utterances", [])
        if not utterances:
            self.stderr.write(self.style.ERROR("No utterances in test set"))
            sys.exit(1)

        # Auto-fill from call if requested
        call_sid = options.get("call_sid")
        call_id = options.get("call_id")
        if call_sid or call_id:
            self._fill_from_call(utterances, call_sid=call_sid, call_id=call_id)
            if options["save"]:
                test_data["utterances"] = utterances
                with open(test_file, "w") as f:
                    json.dump(test_data, f, indent=2)
                self.stdout.write(self.style.SUCCESS(f"Saved to {test_file}"))

        # Compute WER for each utterance
        self.stdout.write("\n" + "=" * 70)
        self.stdout.write("  QWR Voice Bot — Word Error Rate (WER) Report")
        self.stdout.write("=" * 70 + "\n")

        total_ref_words = 0
        total_errors = 0
        results = []
        skipped = 0

        for utt in utterances:
            ref = utt.get("reference", "").strip()
            hyp = utt.get("hypothesis", "").strip()

            if not ref or not hyp:
                skipped += 1
                continue

            result = compute_wer(ref, hyp)
            results.append(result)

            errors = result["substitutions"] + result["insertions"] + result["deletions"]
            total_ref_words += result["ref_words"]
            total_errors += errors

            wer_pct = result["wer"] * 100
            status = "✅" if wer_pct < 15 else ("🟡" if wer_pct < 30 else "❌")

            self.stdout.write(
                f"{status} [{utt.get('id', '?'):>2}] {utt.get('category', ''):>15} | "
                f"WER: {wer_pct:5.1f}% | S={result['substitutions']} "
                f"I={result['insertions']} D={result['deletions']}"
            )
            self.stdout.write(f"     REF: {ref}")
            self.stdout.write(f"     HYP: {hyp}")
            self.stdout.write("")

        # Summary
        self.stdout.write("-" * 70)
        if total_ref_words > 0:
            overall_wer = (total_errors / total_ref_words) * 100
            self.stdout.write(
                f"  Overall WER: {overall_wer:.1f}% "
                f"({total_errors} errors / {total_ref_words} ref words)"
            )
            self.stdout.write(f"  Utterances scored: {len(results)}")
            if skipped:
                self.stdout.write(f"  Utterances skipped (empty hypothesis): {skipped}")

            # Per-category breakdown
            categories = {}
            for utt, result in zip(
                [u for u in utterances if u.get("reference") and u.get("hypothesis")],
                results,
            ):
                cat = utt.get("category", "unknown")
                if cat not in categories:
                    categories[cat] = {"errors": 0, "ref_words": 0, "count": 0}
                categories[cat]["errors"] += (
                    result["substitutions"] + result["insertions"] + result["deletions"]
                )
                categories[cat]["ref_words"] += result["ref_words"]
                categories[cat]["count"] += 1

            if len(categories) > 1:
                self.stdout.write("\n  Per-category WER:")
                for cat, data in sorted(categories.items()):
                    cat_wer = (
                        (data["errors"] / data["ref_words"]) * 100
                        if data["ref_words"]
                        else 0
                    )
                    self.stdout.write(
                        f"    {cat:>15}: {cat_wer:5.1f}% ({data['count']} utterances)"
                    )
        else:
            self.stdout.write(
                "  No utterances with both reference and hypothesis. "
                "Fill in hypotheses first (use --call-sid or manually edit the JSON)."
            )

        self.stdout.write("=" * 70 + "\n")

    def _list_calls(self):
        """List recent calls that have transcripts."""
        calls = (
            Call.objects.filter(turns__isnull=False)
            .distinct()
            .order_by("-created_at")[:15]
        )
        self.stdout.write("\nRecent calls with transcripts:")
        self.stdout.write(f"{'ID':>5} | {'Call SID':>40} | {'From':>15} | {'Turns':>5} | {'Created'}")
        self.stdout.write("-" * 100)
        for call in calls:
            turn_count = call.turns.count()
            self.stdout.write(
                f"{call.id:>5} | {call.call_sid:>40} | "
                f"{call.from_number or '?':>15} | {turn_count:>5} | "
                f"{call.created_at.strftime('%Y-%m-%d %H:%M')}"
            )
        self.stdout.write("")

    def _fill_from_call(self, utterances, *, call_sid=None, call_id=None):
        """Fill hypothesis fields from a call's stored transcripts."""
        if call_sid:
            call = Call.objects.filter(call_sid=call_sid).first()
        elif call_id:
            call = Call.objects.filter(id=call_id).first()
        else:
            return

        if not call:
            self.stderr.write(
                self.style.WARNING(f"Call not found: sid={call_sid} id={call_id}")
            )
            return

        turns = list(
            TranscriptTurn.objects.filter(call=call, speaker="user")
            .order_by("seq_number")
            .values_list("text", flat=True)
        )

        self.stdout.write(
            f"Found {len(turns)} user turns in call {call.call_sid}"
        )

        # Match by position: utterance[i] ↔ turn[i]
        filled = 0
        for i, utt in enumerate(utterances):
            if i < len(turns) and turns[i].strip():
                utt["hypothesis"] = turns[i].strip()
                filled += 1

        self.stdout.write(f"Auto-filled {filled}/{len(utterances)} hypotheses")
