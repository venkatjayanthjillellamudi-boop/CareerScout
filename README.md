\# CareerScout



CareerScout is an autonomous job discovery and verification agent built for the Google All Things Agentic Hackathon.



It helps early-career candidates discover relevant job openings and verifies whether those openings are actually current before presenting them.



\## Problem



Job search is fragmented across company career pages, ATS platforms, and aggregators.



For early-career candidates, this creates three major problems:



\- Search results may be stale

\- Generic career pages may look like valid job postings

\- Candidates may waste time applying to roles that are already closed



CareerScout separates job discovery from job verification.



\## Core Workflow



\*\*Scout → Verify → Explain\*\*



1\. The user provides:

&#x20;  - Resume or background

&#x20;  - Target role

&#x20;  - Location

&#x20;  - Optional work authorization constraints



2\. CareerScout discovers relevant current job candidates.



3\. Every discovered URL is checked independently.



4\. Generic career pages are not automatically treated as active jobs.



5\. When deterministic verification is insufficient, CareerScout uses grounded Gemini verification.



6\. Python validates the final canonical job URL.



7\. Results are classified as:



&#x20;  - Verified Active

&#x20;  - Verified Closed

&#x20;  - Verification Failed



\## Key Reliability Principle



A search result alone is not proof that a job is active.



CareerScout does not treat:



\- HTTP 200

\- a generic careers page

\- an ATS company board

\- an old search result



as sufficient evidence of an active job.



A verified active job must survive the canonical URL and current-status verification pipeline.



\## Technologies Used



\- Python

\- Google ADK

\- Gemini 3.6 Flash

\- Vertex AI

\- Google GenAI SDK

\- Google Search Grounding

\- Google Cloud Run

\- Pydantic

\- Requests



\## Google Cloud Deployment



CareerScout is deployed using Google Cloud Run.



Cloud Run hosts the ADK application while Vertex AI provides access to Gemini.



\## Architecture



See:



\[ARCHITECTURE.md](ARCHITECTURE.md)



\## Project Structure



```text

CareerScout/

│

├── careerscout\_agent/

│   ├── \_\_init\_\_.py

│   ├── agent.py

│   └── requirements.txt

│

├── ARCHITECTURE.md

├── README.md

└── .gitignore

