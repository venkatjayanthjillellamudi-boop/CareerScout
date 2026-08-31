# CareerScout

CareerScout is an autonomous job discovery and verification agent built for the **Google All Things Agentic Hackathon**.

Instead of only returning job search results, CareerScout discovers openings, independently verifies whether the exact posting is still current, resolves canonical application URLs, and separates jobs into trustworthy result states.

**Core workflow:**

**Scout → Verify → Explain**

**Live Cloud Run deployment:**  
https://careerscout-304796106747.us-west1.run.app

---

## Problem

Job searching is fragmented across:

- company career pages
- ATS platforms
- job aggregators
- search engines

For early-career candidates, this creates several problems:

- search results may be stale
- generic career pages may be mistaken for real job postings
- direct application links may be missing or broken
- expired listings may still appear in search results
- candidates may waste time applying to jobs that are already closed
- sponsorship and work authorization information may be unclear

CareerScout was built to separate **job discovery** from **job verification**.

A search result is treated as a lead, not as proof that a job is currently active.

---

## What CareerScout Does

CareerScout can:

- understand a user-provided target role
- infer reasonable early-career role families from a resume
- search the current public web for relevant job openings
- preserve explicit job requirements and sponsorship evidence
- inspect discovered job URLs
- distinguish individual postings from generic company career pages
- perform grounded verification when deterministic checks are insufficient
- resolve canonical direct job URLs
- classify jobs as active, closed, or uncertain
- explain the result back to the user

CareerScout does **not** automatically assume that every discovered result is trustworthy.

---

## Why CareerScout Is Agentic

CareerScout is not a simple chatbot that only generates text.

It performs a multi-step workflow:

**Interpret → Discover → Inspect → Verify → Resolve → Classify → Explain**

The agent:

1. interprets the user's request
2. identifies relevant search criteria
3. invokes a Python job discovery and verification tool
4. uses Gemini with Google Search grounding for live discovery
5. checks job URLs independently with deterministic Python logic
6. escalates ambiguous cases to grounded verification
7. enforces direct canonical job URLs
8. classifies every analyzed job
9. returns structured evidence to the user

This makes CareerScout a **Taskmaster** project because it performs an end-to-end workflow rather than operating as a standard conversational assistant.

---

## Hackathon Category

### Taskmaster

CareerScout handles a messy, multi-step job-search workflow automatically.

Rather than requiring the user to manually:

- search multiple websites
- open each listing
- determine whether the posting is current
- find the real direct application page
- distinguish stale and active jobs

CareerScout performs those steps as one coordinated agent workflow.

---

## Core Workflow

### Scout

CareerScout uses Gemini and Google Search grounding to discover potentially relevant current job openings.

### Verify

Every discovered job enters an independent verification pipeline.

CareerScout checks:

- whether the URL responds
- whether the page is job-specific
- whether the title matches
- whether the company matches
- whether active or closed signals exist
- whether the final URL remains an individual job posting

### Explain

CareerScout returns each analyzed job under one of three states:

- **Verified Active**
- **Verified Closed**
- **Verification Failed**

It also returns evidence explaining why that state was chosen.

---

## Result States

### Verified Active

The exact individual job posting is supported by current evidence and passes CareerScout's canonical URL verification pipeline.

### Verified Closed

Reliable evidence indicates that the posting:

- has been removed
- has expired
- has been filled
- is no longer accepting applications
- or returns a confirmed closed posting response

### Verification Failed

CareerScout could not establish trustworthy current evidence for the exact role.

This does **not** automatically mean the job is fake or unavailable.

It means CareerScout refuses to present the role as confirmed when evidence is insufficient.

---

## Reliability Principle

CareerScout deliberately separates **discovery** from **verification**.

The following are **not enough** to classify a job as active:

- a Google Search result
- an HTTP 200 response
- a company careers homepage
- a generic ATS company board
- an old aggregator listing
- an AI-generated URL without independent validation

A `verified_active` result must survive the canonical URL and current-status verification pipeline.

CareerScout is designed to prefer uncertainty over false confidence.

---

## Architecture

CareerScout uses a hybrid architecture:

- Gemini handles interpretation, discovery, and grounded reasoning
- Python controls mandatory verification rules
- Google ADK coordinates the workflow
- Vertex AI provides Gemini access
- Google Cloud Run hosts the deployed application

Full architecture documentation:

[ARCHITECTURE.md](ARCHITECTURE.md)

---

## Architecture Summary

```text
User
  ↓
ADK Web UI
  ↓
CareerScout ADK Agent
  ↓
search_and_verify_jobs
  ↓
Gemini 3.6 Flash + Google Search Grounding
  ↓
Candidate Job Discovery
  ↓
Deterministic Python URL Verification
  ↓
Grounded Verification when required
  ↓
Canonical URL Enforcement
  ↓
Verified Active / Verified Closed / Verification Failed
  ↓
Explanation returned to user