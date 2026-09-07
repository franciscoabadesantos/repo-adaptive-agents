# Knowledge retrieval

Define the knowledge owner, update process, access boundary, query inputs, and downstream
consumer. Make retrieved context explicit so prompts/Agents distinguish sources, user input,
instructions, and missing evidence. Do not hard-code opaque dataset IDs or private document
details.

Test a permitted fixture set with a clear match, known non-match, ambiguous query, stale or
conflicting source where possible, and retrieval failure. Verify target retrieval, filtering,
reranking, citations, and empty-result behavior when design depends on them.

No-evidence and conflicting-evidence paths must request clarification, report insufficiency,
or escalate. They must not fabricate citations, infer missing records, or authorize a
consequential write. Re-run the fixture set after material changes to documents, chunking,
retrieval settings, model, or prompts.
