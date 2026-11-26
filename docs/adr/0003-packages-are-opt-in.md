# Packages are opt-in; every county is still built

We build every county each release for the public scorecard, but a Package is only handed to a 911
authority or Source agency that opts in through the project's opt-in page, and only then carries that
agency's real domain in its NGUIDs. Pushing unrequested datasets at agencies, or publishing them under
placeholder domains, would read as speaking for them. The opt-in page is also where an agency can take the
sharing paths: submit to the National Address Database, clarify its license, and share with Overture or
Esri Community Maps.

**Amended 2026-11-26 (Ryan, with ADR 0011):** an openly licensed Package is published in the public catalog
before its authority opts in, marked *unclaimed*: under the `.unclaimed.invalid` placeholder domain, titled
and described as not issued by the authority. Opting in still decides who it is handed to and when it carries
the agency's real domain; nothing is pushed at an agency.
