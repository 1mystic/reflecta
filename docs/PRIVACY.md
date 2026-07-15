# Privacy Notice (template)

> This is an honest, engineering-accurate description of what the software does. It is a
> starting template, **not legal advice** — have counsel review before a commercial launch,
> especially for minors (education implicates COPPA/FERPA in the US, GDPR/GDPR-K in the EU,
> and India's DPDP Act 2023).

## What Reflecta collects
When you take a quiz **and give consent**, Reflecta stores, per session:
- the questions shown and the option you chose,
- whether each answer was correct,
- your self-reported confidence and response time,
- the derived analysis (mastery, calibration, gaps, reflection).

## What Reflecta does **not** collect
- No name, email address, phone number, or account.
- No IP address is stored with the session.
- Sessions are keyed by an **opaque random id** with no link to your identity.

## Why (purpose & legal basis)
Data is used solely to generate your reflection and to improve the models that power it.
The legal basis is your **explicit consent**, captured before the quiz starts. Consent is
required by default (`REFLECTA_REQUIRE_CONSENT=true`).

## Retention & deletion
- Sessions are retained for `REFLECTA_SESSION_RETENTION_DAYS` (default 365) and then
  automatically deleted by a retention sweep.
- **Right to erasure:** a session can be deleted at any time via
  `DELETE /api/session/{session_id}`.

## Storage & security
Sessions are stored as anonymous JSON (or a database in production). See `SECURITY.md` for
the security posture. Data is not sold or shared with third parties.

## Children
If deployed to learners under the age of digital consent, obtain verifiable parental/guardian
consent and configure retention accordingly before launch.

## Contact
Reach the maintainer for privacy requests or questions.
