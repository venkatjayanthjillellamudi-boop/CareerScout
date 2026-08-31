# CareerScout

**CareerScout** is an autonomous job discovery and verification agent built for the **Google All Things Agentic Hackathon** in the **Taskmaster** category.

Most job-search tools answer:

> “What jobs can I find?”

CareerScout asks a second question:

> **“Can I prove that this exact job is still active?”**

It searches the current web, discovers relevant openings, independently verifies their source pages, resolves direct canonical job URLs, and separates results into:

- ✅ **Verified Active**
- ❌ **Verified Closed**
- ⚠️ **Verification Failed**

**Core workflow:**  
**Scout → Verify → Explain**

### Live Deployment

https://careerscout-304796106747.us-west1.run.app

### Architecture

See [ARCHITECTURE.md](ARCHITECTURE.md)

---

# The Problem

Job search results are fragmented across:

- employer career sites
- Greenhouse
- Lever
- Ashby
- Workday
- SmartRecruiters
- aggregators
- search engines

A role appearing in search does **not** guarantee that the exact posting is still available.

During development I repeatedly encountered cases where:

- a search result referenced an old role
- a generic company jobs page returned HTTP 200
- a direct job URL returned 404
- an ATS redirected a removed posting to its company board
- a model found the correct role but an unreliable application URL
- sponsorship information was missing or ambiguous

CareerScout was built around one principle:

> **Discovery is not verification.**

---

# What CareerScout Does

A user can provide:

- a target role
- location
- experience level
- explicit work-authorization constraints
- a specific job URL
- or a resume and ask CareerScout to infer reasonable role families

CareerScout then executes a workflow rather than simply generating an answer.

```text
User Request
     ↓
CareerScout ADK Agent
     ↓
Job Discovery
     ↓
Deterministic URL Verification
     ↓
Grounded Verification when necessary
     ↓
Canonical URL Enforcement
     ↓
Verified Active / Closed / Failed
     ↓
Explanation to User
```

---

# Why CareerScout Is Agentic

CareerScout is not a chatbot that simply writes job recommendations.

It performs actions across multiple stages:

1. **Interpret** the user's goal
2. **Discover** current job candidates
3. **Inspect** source URLs
4. **Verify** current status
5. **Search again** when evidence is insufficient
6. **Resolve** the canonical individual posting
7. **Enforce** deterministic verification rules
8. **Classify** the result
9. **Explain** what was established

This is why CareerScout fits the **Taskmaster** track: it executes a complete multi-step workflow.

---

# Architecture

CareerScout uses a hybrid AI + deterministic architecture.

## Google ADK

Google ADK acts as the agent orchestration layer.

The root CareerScout agent interprets the request and invokes one public Python function tool:

```text
search_and_verify_jobs
```

## Gemini 3.6 Flash on Vertex AI

Gemini handles:

- request interpretation
- live job discovery
- grounded search reasoning
- ambiguous-job investigation
- extraction of job requirements and evidence

## Google Search Grounding

Google Search grounding provides current public-web evidence during:

- job discovery
- fallback verification
- canonical posting resolution

## Deterministic Python Verification

Python controls mandatory verification behavior.

This is intentional: critical verification rules are not left entirely to model instructions.

Python checks include:

- HTTP/HTTPS validation
- hostname validation
- protection against private/internal network URLs
- HTTP response inspection
- redirects
- job-specific vs generic URL detection
- title matching
- company matching
- active/closed page signals
- canonical URL validation

## Google Cloud Run

The ADK application is deployed on **Google Cloud Run**.

## Google Cloud Build / Artifact Registry

The Cloud Run deployment uses Google Cloud Build and Artifact Registry to build and store the application container.

---

# Verification Pipeline

## 1. Discovery

Gemini + Google Search grounding discovers current candidate jobs.

Discovery prefers:

1. official employer job page
2. official ATS posting
3. generic employer/ATS board only when an exact URL cannot yet be found
4. aggregator only when necessary

A discovered result is **not automatically trusted**.

---

## 2. Initial Deterministic Check

Python checks the discovered URL.

CareerScout looks for:

- valid public URL
- HTTP response
- final redirected URL
- job-specific URL structure
- expected title/company
- active or closed signals

If deterministic evidence is strong enough, CareerScout can classify the page without additional search.

---

## 3. Grounded Verification

If the initial page is:

- generic
- ambiguous
- access-limited
- missing sufficient evidence

CareerScout performs another grounded Gemini + Google Search verification.

The verifier searches for the **exact individual job posting**.

---

## 4. Canonical URL Enforcement

Before a job is allowed to become `verified_active`, Python independently checks the canonical URL returned by the verifier.

A job cannot become Verified Active merely because:

```text
HTTP status = 200
```

or because the URL looks like:

```text
company.com/careers
jobs.ashbyhq.com/company
job-boards.greenhouse.io/company
```

CareerScout requires evidence for the **specific individual posting**.

---

# Result States

## ✅ Verified Active

Used when CareerScout establishes trustworthy current evidence for the exact individual job posting.

The result should include a canonical direct job URL.

---

## ❌ Verified Closed

Used when reliable evidence indicates that the exact posting:

- returned 404/410
- was removed
- was filled
- expired
- stopped accepting applications
- or explicitly states that it is closed

---

## ⚠️ Verification Failed

Used when CareerScout cannot establish trustworthy current status.

Examples:

- only a generic company careers page exists
- only a generic ATS board is available
- evidence conflicts
- the canonical posting cannot be located
- the page cannot be reliably inspected

**Verification Failed does not automatically mean the job is fake or closed.**

It means CareerScout refuses to present uncertain evidence as fact.

---

# Resume-Based Search

CareerScout can also work without the user explicitly specifying a job title.

A user can provide a resume and ask:

```text
Based only on my resume, identify reasonable entry-level or
early-career roles related to my demonstrated skills and projects,
then search for current openings in the San Francisco Bay Area.
```

CareerScout is instructed to:

- use only evidence actually present in the resume
- not invent candidate skills
- keep projects classified as projects
- not transform project work into professional employment

It can then derive reasonable role families before invoking the normal discovery and verification workflow.

---

# Work Authorization & Sponsorship

CareerScout does **not** infer immigration or visa compatibility.

Employer/source evidence is represented as:

```text
explicitly_supported
explicitly_not_supported
unclear
```

When explicit evidence cannot be found, CareerScout returns:

```text
unclear
```

instead of guessing.

---

# Technologies

## Google / AI

- Google ADK
- Gemini 3.6 Flash
- Vertex AI
- Google GenAI SDK
- Google Search Grounding

## Google Cloud

- Google Cloud Run
- Google Cloud Build
- Artifact Registry
- Vertex AI

## Backend

- Python
- Pydantic
- Requests

## Development

- Git
- GitHub
- Google Cloud CLI
- ADK CLI
- PowerShell

---

# Project Structure

```text
CareerScout/
│
├── careerscout_agent/
│   ├── __init__.py
│   ├── agent.py
│   └── requirements.txt
│
├── ARCHITECTURE.md
├── README.md
└── .gitignore
```

---

# Local Setup

## Prerequisites

Recommended:

- Python 3.12
- Google Cloud CLI
- Google Cloud project with Vertex AI enabled
- Google credentials with permission to use Vertex AI

---

## 1. Clone the repository

```powershell
git clone https://github.com/venkatjayanthjillellamudi-boop/CareerScout.git
cd CareerScout
```

---

## 2. Create a virtual environment

```powershell
python -m venv .venv
```

---

## 3. Install dependencies

```powershell
.\.venv\Scripts\pip.exe install -r .\careerscout_agent\requirements.txt
```

---

## 4. Authenticate with Google Cloud

On Windows PowerShell:

```powershell
gcloud.cmd auth application-default login
```

---

## 5. Configure the Google Cloud project

```powershell
$env:GOOGLE_CLOUD_PROJECT="YOUR_PROJECT_ID"
$env:GOOGLE_CLOUD_LOCATION="global"
```

The application reads the project from environment variables. No project credentials are stored in the repository.

---

## 6. Enable Vertex AI if necessary

```powershell
gcloud.cmd services enable aiplatform.googleapis.com
```

---

## 7. Start CareerScout

```powershell
.\.venv\Scripts\adk.exe web --port 8080 --no-reload
```

Open:

```text
http://127.0.0.1:8080
```

Select:

```text
careerscout_agent
```

and create a new session.

---

# Reproducible Testing Instructions

CareerScout works with the **live public web**.

Therefore, reproducibility means that the **agent workflow and verification rules should reproduce consistently**.

It does **not** mean that identical companies or job openings will be returned later, because real job postings change continuously.

---

## Test 1 — Standard Job Discovery

### Prompt

```text
Find entry-level AI Engineer jobs in the San Francisco Bay Area
and verify the openings.
```

### Expected workflow

CareerScout should:

```text
Interpret request
     ↓
Call search_and_verify_jobs
     ↓
Discover current candidates
     ↓
Check each source URL
     ↓
Perform grounded verification when needed
     ↓
Enforce canonical URLs
     ↓
Return categorized results
```

### Expected output categories

At least one or more of:

```text
Verified Active
Verified Closed
Verification Failed
```

The exact jobs returned may differ based on current web data.

---

## Test 2 — Resume-Based Autonomous Role Discovery

Upload or paste a resume.

### Prompt

```text
Based only on my resume, identify reasonable entry-level or
early-career roles related to my demonstrated skills and projects,
then search for current openings in the San Francisco Bay Area.

Do not invent skills or professional experience.
```

### Expected behavior

CareerScout should:

- derive reasonable role families from resume evidence
- explicitly preserve projects as projects
- avoid inventing employment
- perform job discovery
- verify discovered openings
- return the standard result categories

The user should **not need to specify a job title manually**.

---

## Test 3 — Verify One Specific Job

Provide a direct job URL.

### Prompt

```text
Verify whether this job is currently active:

<PASTE_JOB_URL>
```

### Expected behavior

CareerScout should skip broad job discovery and directly run the verification pipeline.

The result should be one of:

```text
verified_active
verified_closed
verification_failed
```

---

## Test 4 — Generic ATS Safety Test

Use a generic ATS/company board rather than an individual posting.

Example format:

```text
https://jobs.ashbyhq.com/<company>
```

### Expected behavior

CareerScout must **not** classify the generic board itself as `verified_active`.

It should attempt to locate the exact posting.

If it cannot establish the individual canonical job URL:

```text
verification_failed
```

is the expected safe result.

---

## Test 5 — Removed Job Test

Provide a known removed or expired individual job URL.

### Expected behavior

If the specific URL reliably returns evidence such as HTTP `404` or `410`, CareerScout should normally classify it as:

```text
verified_closed
```

If evidence is ambiguous instead:

```text
verification_failed
```

is acceptable.

The system should **not** label uncertain evidence as active.

---

# What Successful Testing Demonstrates

The important behavior to reproduce is:

```text
Search evidence
      ≠
Verified truth
```

CareerScout should consistently enforce:

```text
Discovery
   ↓
Independent Verification
   ↓
Canonical URL Validation
   ↓
Evidence-Based Classification
```

A judge does not need to receive exactly the same job results shown in the demo.

The verification behavior is the reproducible part of the system.

---

# Cloud Run Deployment

Enable required services:

```powershell
gcloud.cmd services enable `
run.googleapis.com `
cloudbuild.googleapis.com `
artifactregistry.googleapis.com `
aiplatform.googleapis.com
```

Deploy with ADK:

```powershell
.\.venv\Scripts\adk.exe deploy cloud_run `
--project=YOUR_PROJECT_ID `
--region=us-west1 `
--service_name=careerscout `
--app_name=careerscout_agent `
--with_ui `
.\careerscout_agent `
-- `
--allow-unauthenticated `
--set-env-vars=GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID,GOOGLE_CLOUD_LOCATION=global `
--min-instances=0 `
--max-instances=1
```

The Cloud Run runtime service account must have permission to invoke Vertex AI models.

For example:

```text
roles/aiplatform.user
```

IAM configuration depends on the Google Cloud project and organization.

---

# Demo

The hackathon demo demonstrates:

1. the public Cloud Run deployment
2. CareerScout receiving a job-search request
3. the ADK agent invoking `search_and_verify_jobs`
4. current-web discovery using Gemini + Google Search
5. deterministic verification
6. rejected uncertain/generic postings
7. Verified Active results with canonical URLs
8. Cloud Run deployment proof

---

# Key Engineering Learnings

## Structured Output Is Not Truth

Valid JSON guarantees structure, not factual correctness.

This is why Pydantic validation alone cannot solve hallucination.

---

## HTTP 200 Is Not Enough

A deleted job can redirect to a generic careers board that still returns HTTP 200.

CareerScout verifies page identity and canonical URLs instead.

---

## Search and Verification Are Different Tasks

A search result is evidence that a role may exist.

It is not proof that applications are still being accepted.

---

## Critical Rules Should Live in Code

Instructions such as:

> “Always verify the job”

are not enough by themselves.

Mandatory verification is controlled by deterministic Python execution.

---

## Simpler Architecture Improved Reliability

Early experiments with nested/multiple agent workflows introduced unnecessary complexity and execution issues.

The final MVP uses:

```text
One ADK Agent
      +
One Public Python Tool
      +
Deterministic Internal Pipeline
```

This made execution easier to reason about and verify.

---

# Current MVP Scope

Implemented:

- ✅ resume-informed role interpretation
- ✅ current-web job discovery
- ✅ Google Search grounding
- ✅ direct URL checking
- ✅ deterministic verification
- ✅ grounded fallback verification
- ✅ canonical URL enforcement
- ✅ Verified Active / Closed / Failed states
- ✅ explicit sponsorship evidence handling
- ✅ Cloud Run deployment
- ✅ Google ADK integration

Not implemented in the current MVP:

- candidate qualification scoring
- automatic application submission
- persistent job history
- persistent user profiles
- application tracking
- long-running background monitoring
- exhaustive market coverage

---

# Future Work

Potential next steps:

- candidate-to-job evidence mapping
- deterministic qualification scoring
- Recommended / Worth Applying / Stretch classifications
- persistent job history
- company-first employer discovery
- application tracking
- scheduled job monitoring
- personalized alerts
- market intelligence
- persistent user preferences

---

# Repository

https://github.com/venkatjayanthjillellamudi-boop/CareerScout

# Live Application

https://careerscout-304796106747.us-west1.run.app

# Author

**Venkat Jayanth J**

Built for the **Google All Things Agentic Hackathon**.