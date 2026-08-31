\# CareerScout Architecture



CareerScout is an autonomous job discovery and verification agent built with Google ADK, Gemini, Vertex AI, Google Search grounding, deterministic Python verification, and Google Cloud Run.



```mermaid

flowchart TD



&#x20;   U\[User]

&#x20;   UI\[ADK Web UI]

&#x20;   CR\[Google Cloud Run]

&#x20;   A\[CareerScout ADK Agent]

&#x20;   T\[search\_and\_verify\_jobs Tool]



&#x20;   D\[Job Discovery]

&#x20;   G\[Gemini 3.6 Flash on Vertex AI]

&#x20;   S\[Google Search Grounding]



&#x20;   V\[Python URL Verification]

&#x20;   GV\[Grounded Job Verification]

&#x20;   C\[Canonical URL Enforcement]



&#x20;   ACTIVE\[Verified Active]

&#x20;   CLOSED\[Verified Closed]

&#x20;   FAILED\[Verification Failed]



&#x20;   U --> UI

&#x20;   UI --> CR

&#x20;   CR --> A

&#x20;   A --> T



&#x20;   T --> D

&#x20;   D --> G

&#x20;   G --> S



&#x20;   D --> V



&#x20;   V -->|Strong deterministic evidence| C

&#x20;   V -->|Evidence insufficient| GV



&#x20;   GV --> G

&#x20;   GV --> S

&#x20;   GV --> C



&#x20;   C -->|Exact posting + current evidence| ACTIVE

&#x20;   C -->|Closed / removed evidence| CLOSED

&#x20;   C -->|Cannot establish trustworthy status| FAILED

```



\## Core Workflow



\*\*Scout → Verify → Explain\*\*



1\. User provides a resume, target role, location, or constraints.

2\. CareerScout interprets the request through Google ADK.

3\. `search\_and\_verify\_jobs` executes the workflow.

4\. Gemini 3.6 Flash with Google Search grounding discovers current job candidates.

5\. Python checks every discovered URL.

6\. Generic career pages are not accepted as verified active postings.

7\. When deterministic verification is insufficient, Gemini performs grounded verification.

8\. Python enforces the final canonical job URL.

9\. Results are classified as:

&#x20;  - Verified Active

&#x20;  - Verified Closed

&#x20;  - Verification Failed



\## Google Cloud Components



\- \*\*Google Cloud Run\*\* — deployed application runtime

\- \*\*Vertex AI\*\* — Gemini model access

\- \*\*Google ADK\*\* — agent orchestration and tool execution

\- \*\*Google Search Grounding\*\* — live web discovery and verification support



\## Reliability Principle



CareerScout separates job discovery from job verification.



A search result, HTTP 200 response, or generic company career page alone is not enough to classify a job as active.



A `verified\_active` result must survive CareerScout's canonical URL and current-status verification pipeline.



