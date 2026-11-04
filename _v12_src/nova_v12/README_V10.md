# NOVA v1.0 — Transaction reasoning upgrade

Local prototype, not the cloud NCA. Adds supported refund, repayment and returned-money patterns with validation against earlier transfers. Rejects unmatched or excessive refunds. Preserves raw reasoning and model handoff. Narrow parser: no general loan semantics, pronoun resolution or arbitrary language. VERIFIED is only within the parser assumptions.

Run: python -W error::ResourceWarning -m unittest discover -s tests -q
