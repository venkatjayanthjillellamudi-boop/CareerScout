import html
import ipaddress
import json
import os
import re
import socket
import time
from datetime import date
from typing import Dict, List, Literal, Optional
from urllib.parse import urlparse

import requests
from pydantic import BaseModel, Field

from google import genai
from google.genai.types import (
    GenerateContentConfig,
    GoogleSearch,
    HttpOptions,
    HttpRetryOptions,
    Tool,
)

from google.adk.agents import Agent


# =========================================================
# CONFIGURATION
# =========================================================

MODEL = "gemini-3.6-flash"


client = genai.Client(
    vertexai=True,
    project=os.environ["GOOGLE_CLOUD_PROJECT"],
    location=os.environ.get(
        "GOOGLE_CLOUD_LOCATION",
        "global",
    ),
    http_options=HttpOptions(
        api_version="v1",
        retry_options=HttpRetryOptions(
            attempts=5,
            initial_delay=2.0,
            max_delay=20.0,
            exp_base=2.0,
            http_status_codes=[
                429,
                500,
                502,
                503,
                504,
            ],
        ),
    ),
)


# =========================================================
# DATA MODELS
# =========================================================


class JobRecord(BaseModel):
    job_title: str
    company: str
    location: str
    workplace_type: str

    source_name: str

    source_type: Literal[
        "company_career_page",
        "greenhouse",
        "lever",
        "ashby",
        "workday",
        "smartrecruiters",
        "other_ats",
        "aggregator",
        "other",
    ]

    job_url: str
    posting_date: str

    experience_requirement: str
    education_requirement: str

    work_authorization_requirement: str

    sponsorship_status: Literal[
        "explicitly_supported",
        "explicitly_not_supported",
        "unclear",
    ]

    sponsorship_evidence: str
    search_relevance_reason: str


class JobSearchResponse(BaseModel):
    jobs: List[JobRecord]

    search_notes: List[str] = Field(
        default_factory=list
    )


class JobVerificationResponse(BaseModel):
    verification_status: Literal[
        "verified_active",
        "verified_closed",
        "verification_failed",
    ]

    verification_method: Literal[
        "deterministic_page",
        "grounded_gemini",
        "pipeline_failure",
    ]

    grounded_search_used: bool
    url_check_performed: bool

    canonical_job_url: str

    verified_title: str
    verified_company: str
    verified_location: str

    url_page_responded: bool
    http_status: str

    status_evidence: str

    experience_requirement: str
    education_requirement: str

    work_authorization_requirement: str

    sponsorship_status: Literal[
        "explicitly_supported",
        "explicitly_not_supported",
        "unclear",
    ]

    sponsorship_evidence: str

    verification_notes: List[str] = Field(
        default_factory=list
    )


class VerifiedJobResult(BaseModel):
    discovered_job: JobRecord
    verification: JobVerificationResponse


class SearchAndVerifyResponse(BaseModel):
    mode: Literal[
        "job_discovery",
        "single_job_verification",
    ]

    verified_active: List[VerifiedJobResult]

    verified_closed: List[VerifiedJobResult]

    verification_failed: List[VerifiedJobResult]

    stats: Dict[str, int]

    search_notes: List[str] = Field(
        default_factory=list
    )


# =========================================================
# JSON HELPER
# =========================================================


def _extract_json(text: str) -> dict:
    """
    Extract one JSON object from Gemini output.
    """

    cleaned = text.strip()

    cleaned = re.sub(
        r"^```(?:json)?\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )

    cleaned = re.sub(
        r"\s*```$",
        "",
        cleaned,
    )

    match = re.search(
        r"\{.*\}",
        cleaned,
        flags=re.DOTALL,
    )

    if not match:
        raise ValueError(
            "Gemini response did not contain JSON."
        )

    return json.loads(
        match.group(0)
    )


# =========================================================
# TEXT HELPERS
# =========================================================


def _normalize_text(
    value: str,
) -> str:

    value = value.lower()

    value = re.sub(
        r"[^a-z0-9]+",
        " ",
        value,
    )

    return re.sub(
        r"\s+",
        " ",
        value,
    ).strip()


def _important_tokens(
    value: str,
) -> set:

    stop_words = {
        "the",
        "and",
        "or",
        "of",
        "at",
        "in",
        "for",
        "to",
        "a",
        "an",
        "inc",
        "llc",
        "company",
    }

    return {
        token
        for token
        in _normalize_text(value).split()
        if (
            len(token) > 2
            and token not in stop_words
        )
    }


def _text_matches(
    expected: str,
    page_text: str,
    minimum_ratio: float = 0.60,
) -> bool:

    if (
        not expected
        or expected.lower() == "unknown"
    ):
        return False

    expected_tokens = (
        _important_tokens(
            expected
        )
    )

    if not expected_tokens:
        return False

    page_tokens = (
        _important_tokens(
            page_text
        )
    )

    matched = (
        expected_tokens.intersection(
            page_tokens
        )
    )

    ratio = (
        len(matched)
        / len(expected_tokens)
    )

    return ratio >= minimum_ratio


# =========================================================
# URL HELPERS
# =========================================================


def _is_generic_career_url(
    job_url: str,
) -> bool:
    """
    Detect obviously generic company career/job pages.

    Examples that should return True:

    https://mercor.com/careers

    https://jobs.ashbyhq.com/mintlify

    https://job-boards.greenhouse.io/wonderschool
    """

    try:
        parsed = urlparse(
            job_url
        )

        path = (
            parsed.path
            .lower()
            .rstrip("/")
        )

        generic_paths = {
            "",
            "/careers",
            "/career",
            "/jobs",
            "/job",
            "/openings",
            "/positions",
            "/opportunities",
            "/careers/jobs",
            "/careers/openings",
        }

        return path in generic_paths

    except Exception:
        return True


def _looks_like_specific_job_url(
    job_url: str,
) -> bool:
    """
    Determine whether URL appears to represent one
    specific job posting instead of a company job board.

    This is intentionally conservative.
    """

    try:
        parsed = urlparse(
            job_url
        )

        if parsed.scheme not in {
            "http",
            "https",
        }:
            return False

        host = (
            parsed.hostname or ""
        ).lower()

        path = (
            parsed.path or ""
        )

        parts = [
            part
            for part
            in path.split("/")
            if part
        ]

        # -------------------------------------------------
        # Obvious generic career pages
        # -------------------------------------------------

        if _is_generic_career_url(
            job_url
        ):
            return False

        # -------------------------------------------------
        # Ashby
        #
        # Generic:
        # jobs.ashbyhq.com/mintlify
        #
        # Specific:
        # jobs.ashbyhq.com/Mintlify/<job-id>
        # -------------------------------------------------

        if "ashbyhq.com" in host:
            return len(parts) >= 2

        # -------------------------------------------------
        # Greenhouse
        #
        # Generic:
        # job-boards.greenhouse.io/wonderschool
        #
        # Specific:
        # job-boards.greenhouse.io/wonderschool/jobs/123
        # -------------------------------------------------

        if "greenhouse.io" in host:
            lowered_path = path.lower()

            return (
                "/jobs/"
                in lowered_path
            )

        # -------------------------------------------------
        # Lever
        #
        # Generic:
        # jobs.lever.co/company
        #
        # Specific:
        # jobs.lever.co/company/<job-id>
        # -------------------------------------------------

        if "lever.co" in host:
            return len(parts) >= 2

        # -------------------------------------------------
        # SmartRecruiters
        # -------------------------------------------------

        if "smartrecruiters.com" in host:
            return len(parts) >= 2

        # -------------------------------------------------
        # Workday
        #
        # Exact job pages normally contain /job/
        # -------------------------------------------------

        if (
            "myworkdayjobs.com" in host
            or "workdayjobs.com" in host
        ):
            return (
                "/job/"
                in path.lower()
            )

        # -------------------------------------------------
        # LinkedIn job view
        # -------------------------------------------------

        if "linkedin.com" in host:
            return (
                "/jobs/view/"
                in path.lower()
            )

        # -------------------------------------------------
        # Unknown employer site
        #
        # Reject only obvious generic pages.
        # A deeper URL may be a specific employer posting.
        # -------------------------------------------------

        return not _is_generic_career_url(
            job_url
        )

    except Exception:
        return False


# =========================================================
# MANDATORY URL CHECK
# =========================================================


def _check_job_url(
    job_url: str,
) -> dict:
    """
    Internal deterministic URL/page inspection.

    Every job verification passes through here.

    This function is NOT exposed to Gemini as an ADK tool.
    """

    result = {
        "requested_url": job_url,
        "page_responded": False,
        "http_status": "unknown",
        "final_url": "unknown",
        "page_title": "unknown",
        "text_preview": "",
        "access_limited": False,
        "looks_specific": False,
        "error": None,
    }

    try:
        parsed = urlparse(
            job_url
        )

        # -------------------------------------------------
        # Protocol
        # -------------------------------------------------

        if parsed.scheme not in {
            "http",
            "https",
        }:
            result["error"] = (
                "Only HTTP/HTTPS URLs are allowed."
            )

            return result

        hostname = parsed.hostname

        if not hostname:
            result["error"] = (
                "URL has no hostname."
            )

            return result

        if (
            hostname.lower()
            == "localhost"
        ):
            result["error"] = (
                "Localhost URLs are not allowed."
            )

            return result

        # -------------------------------------------------
        # Prevent requests to private/internal networks
        # -------------------------------------------------

        try:
            addresses = (
                socket.getaddrinfo(
                    hostname,
                    None,
                )
            )

            for address in addresses:
                ip_string = (
                    address[4][0]
                )

                ip_obj = (
                    ipaddress.ip_address(
                        ip_string
                    )
                )

                if (
                    ip_obj.is_private
                    or ip_obj.is_loopback
                    or ip_obj.is_link_local
                    or ip_obj.is_reserved
                ):
                    result["error"] = (
                        "URL resolves to a "
                        "non-public network address."
                    )

                    return result

        except socket.gaierror:
            result["error"] = (
                "Hostname could not be resolved."
            )

            return result

        # -------------------------------------------------
        # HTTP request
        # -------------------------------------------------

        response = requests.get(
            job_url,
            timeout=15,
            allow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 "
                    "CareerScout Job Verification"
                )
            },
        )

        result[
            "page_responded"
        ] = True

        result[
            "http_status"
        ] = str(
            response.status_code
        )

        result[
            "final_url"
        ] = response.url

        result[
            "access_limited"
        ] = (
            response.status_code
            in {
                401,
                403,
                429,
            }
        )

        result[
            "looks_specific"
        ] = (
            _looks_like_specific_job_url(
                response.url
            )
        )

        raw_html = (
            response.text[:200000]
        )

        # -------------------------------------------------
        # HTML title
        # -------------------------------------------------

        title_match = re.search(
            r"<title[^>]*>(.*?)</title>",
            raw_html,
            (
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        if title_match:
            result[
                "page_title"
            ] = html.unescape(
                re.sub(
                    r"\s+",
                    " ",
                    title_match.group(1),
                ).strip()
            )

        # -------------------------------------------------
        # Strip script/style/html tags
        # -------------------------------------------------

        cleaned = re.sub(
            r"<script.*?</script>",
            " ",
            raw_html,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        cleaned = re.sub(
            r"<style.*?</style>",
            " ",
            cleaned,
            flags=(
                re.IGNORECASE
                | re.DOTALL
            ),
        )

        cleaned = re.sub(
            r"<[^>]+>",
            " ",
            cleaned,
        )

        cleaned = (
            html.unescape(
                cleaned
            )
        )

        cleaned = re.sub(
            r"\s+",
            " ",
            cleaned,
        ).strip()

        result[
            "text_preview"
        ] = cleaned[:12000]

        return result

    except requests.RequestException as exc:
        result[
            "error"
        ] = str(
            exc
        )

        return result


# =========================================================
# CHEAP DETERMINISTIC VERIFICATION
# =========================================================


def _cheap_page_verdict(
    job: JobRecord,
    url_check: dict,
) -> Optional[
    JobVerificationResponse
]:

    # -----------------------------------------------------
    # Could not reach URL
    # -----------------------------------------------------

    if not url_check[
        "page_responded"
    ]:
        return JobVerificationResponse(
            verification_status=(
                "verification_failed"
            ),
            verification_method=(
                "deterministic_page"
            ),
            grounded_search_used=False,
            url_check_performed=True,
            canonical_job_url=(
                job.job_url
            ),
            verified_title=(
                job.job_title
            ),
            verified_company=(
                job.company
            ),
            verified_location=(
                job.location
            ),
            url_page_responded=False,
            http_status=(
                url_check[
                    "http_status"
                ]
            ),
            status_evidence=(
                "The supplied job URL did not "
                "successfully return a page."
            ),
            experience_requirement=(
                job.experience_requirement
            ),
            education_requirement=(
                job.education_requirement
            ),
            work_authorization_requirement=(
                job.work_authorization_requirement
            ),
            sponsorship_status=(
                job.sponsorship_status
            ),
            sponsorship_evidence=(
                job.sponsorship_evidence
            ),
            verification_notes=[
                (
                    url_check.get(
                        "error"
                    )
                    or "URL check failed."
                )
            ],
        )

    status_code = (
        url_check[
            "http_status"
        ]
    )

    # -----------------------------------------------------
    # Exact posting removed
    #
    # Important:
    # Generic pages are NOT closed merely because
    # some URL returns an error.
    # -----------------------------------------------------

    if (
        status_code in {
            "404",
            "410",
        }
        and url_check[
            "looks_specific"
        ]
    ):
        return JobVerificationResponse(
            verification_status=(
                "verified_closed"
            ),
            verification_method=(
                "deterministic_page"
            ),
            grounded_search_used=False,
            url_check_performed=True,
            canonical_job_url=(
                url_check[
                    "final_url"
                ]
            ),
            verified_title=(
                job.job_title
            ),
            verified_company=(
                job.company
            ),
            verified_location=(
                job.location
            ),
            url_page_responded=True,
            http_status=(
                status_code
            ),
            status_evidence=(
                "The specific job URL returned "
                f"HTTP {status_code}."
            ),
            experience_requirement=(
                job.experience_requirement
            ),
            education_requirement=(
                job.education_requirement
            ),
            work_authorization_requirement=(
                job.work_authorization_requirement
            ),
            sponsorship_status=(
                job.sponsorship_status
            ),
            sponsorship_evidence=(
                job.sponsorship_evidence
            ),
            verification_notes=[],
        )

    # -----------------------------------------------------
    # Access blocked
    #
    # Grounded verification may still resolve it.
    # -----------------------------------------------------

    if url_check[
        "access_limited"
    ]:
        return None

    # -----------------------------------------------------
    # CRITICAL RULE
    #
    # A generic company/ATS board can NEVER become
    # verified_active here.
    #
    # Grounded verifier must locate exact canonical URL.
    # -----------------------------------------------------

    if not url_check[
        "looks_specific"
    ]:
        return None

    page_text = (
        url_check[
            "page_title"
        ]
        + " "
        + url_check[
            "text_preview"
        ]
    )

    normalized = (
        _normalize_text(
            page_text
        )
    )

    title_matches = (
        _text_matches(
            job.job_title,
            page_text,
        )
    )

    company_matches = (
        _text_matches(
            job.company,
            page_text,
            minimum_ratio=0.50,
        )
    )

    identity_matches = (
        title_matches
        and company_matches
    )

    # -----------------------------------------------------
    # Closed signals
    # -----------------------------------------------------

    closed_signals = [
        "this job is no longer available",
        "this position has been filled",
        "position has been filled",
        "job has been filled",
        "no longer accepting applications",
        "applications are closed",
        "application period has closed",
        "this job has expired",
        "job posting has expired",
        "position is closed",
        "requisition closed",
    ]

    closed_signal = next(
        (
            signal
            for signal
            in closed_signals
            if signal
            in normalized
        ),
        None,
    )

    if (
        identity_matches
        and closed_signal
    ):
        return JobVerificationResponse(
            verification_status=(
                "verified_closed"
            ),
            verification_method=(
                "deterministic_page"
            ),
            grounded_search_used=False,
            url_check_performed=True,
            canonical_job_url=(
                url_check[
                    "final_url"
                ]
            ),
            verified_title=(
                job.job_title
            ),
            verified_company=(
                job.company
            ),
            verified_location=(
                job.location
            ),
            url_page_responded=True,
            http_status=(
                status_code
            ),
            status_evidence=(
                "The specific job page matches "
                "the title/company and contains "
                "the closed signal: "
                f"'{closed_signal}'."
            ),
            experience_requirement=(
                job.experience_requirement
            ),
            education_requirement=(
                job.education_requirement
            ),
            work_authorization_requirement=(
                job.work_authorization_requirement
            ),
            sponsorship_status=(
                job.sponsorship_status
            ),
            sponsorship_evidence=(
                job.sponsorship_evidence
            ),
            verification_notes=[],
        )

    # -----------------------------------------------------
    # Active signals
    # -----------------------------------------------------

    active_signals = [
        "apply for this job",
        "apply for this position",
        "submit application",
        "apply now",
        "start application",
        "submit your application",
    ]

    active_signal = next(
        (
            signal
            for signal
            in active_signals
            if signal
            in normalized
        ),
        None,
    )

    if (
        status_code == "200"
        and identity_matches
        and active_signal
        and url_check[
            "looks_specific"
        ]
    ):
        return JobVerificationResponse(
            verification_status=(
                "verified_active"
            ),
            verification_method=(
                "deterministic_page"
            ),
            grounded_search_used=False,
            url_check_performed=True,
            canonical_job_url=(
                url_check[
                    "final_url"
                ]
            ),
            verified_title=(
                job.job_title
            ),
            verified_company=(
                job.company
            ),
            verified_location=(
                job.location
            ),
            url_page_responded=True,
            http_status=(
                status_code
            ),
            status_evidence=(
                "The direct job-specific page "
                "matches the title/company and "
                "contains an active application "
                f"signal: '{active_signal}'."
            ),
            experience_requirement=(
                job.experience_requirement
            ),
            education_requirement=(
                job.education_requirement
            ),
            work_authorization_requirement=(
                job.work_authorization_requirement
            ),
            sponsorship_status=(
                job.sponsorship_status
            ),
            sponsorship_evidence=(
                job.sponsorship_evidence
            ),
            verification_notes=[
                (
                    "Grounded verification was "
                    "not required because a specific "
                    "job page provided sufficient "
                    "positive evidence."
                )
            ],
        )

    return None


# =========================================================
# GEMINI + GOOGLE SEARCH
# =========================================================


def _grounded_gemini(
    prompt: str,
) -> str:

    response = (
        client.models.generate_content(
            model=MODEL,
            contents=prompt,
            config=GenerateContentConfig(
                tools=[
                    Tool(
                        google_search=(
                            GoogleSearch()
                        )
                    )
                ],
            ),
        )
    )

    return response.text or ""


# =========================================================
# INTERNAL JOB DISCOVERY
# =========================================================


def _search_jobs_internal(
    role_query: str,
    location: str,
    experience_level: str,
    work_authorization: str,
    max_results: int,
) -> JobSearchResponse:

    max_results = max(
        1,
        min(
            max_results,
            10,
        ),
    )

    prompt = f"""
You are CareerScout's factual job discovery engine.

TODAY:
{date.today().isoformat()}

Search the CURRENT public web.


TARGET ROLES:
{role_query}


LOCATION:
{location}


EXPERIENCE PREFERENCE:
{experience_level}


USER-PROVIDED WORK AUTHORIZATION CONSTRAINT:
{work_authorization}


MAXIMUM RESULTS:
{max_results}


==================================================
PURPOSE
==================================================

Your job is DISCOVERY.

Verification happens after you return candidates.


==================================================
RULES
==================================================

Return only job openings supported by current
search evidence.

Prefer:

1. Exact official employer job URL
2. Exact official ATS job URL
3. Generic official company/ATS board only when
   an exact posting URL cannot yet be found
4. Aggregator only when necessary


When possible, every candidate should contain
the DIRECT URL for that specific posting.

Examples of GOOD URLs:

jobs.ashbyhq.com/company/<specific-job-id>

job-boards.greenhouse.io/company/jobs/<job-id>

jobs.lever.co/company/<job-id>


Examples of GENERIC URLs:

jobs.ashbyhq.com/company

job-boards.greenhouse.io/company

company.com/careers


A generic URL may be returned during discovery
ONLY when the role itself is supported by search
evidence and an exact URL could not be identified.

The verification stage will then attempt to resolve
the canonical exact posting.


Preserve the source's actual:

- title
- company
- location
- experience requirement
- education requirement
- work authorization language
- sponsorship language


Do not soften requirements.

Do not infer:

- OPT
- STEM OPT
- CPT
- H-1B
- citizenship
- permanent residency
- sponsorship


sponsorship_status must be exactly:

explicitly_supported
explicitly_not_supported
unclear


Use "unknown" when evidence is unavailable.

Do NOT determine candidate qualification.

Returning fewer trustworthy candidates is better
than inventing jobs.


==================================================
OUTPUT
==================================================

Return ONLY JSON:

{{
  "jobs": [
    {{
      "job_title": "...",
      "company": "...",
      "location": "...",
      "workplace_type": "...",
      "source_name": "...",
      "source_type": "company_career_page | greenhouse | lever | ashby | workday | smartrecruiters | other_ats | aggregator | other",
      "job_url": "...",
      "posting_date": "...",
      "experience_requirement": "...",
      "education_requirement": "...",
      "work_authorization_requirement": "...",
      "sponsorship_status": "explicitly_supported | explicitly_not_supported | unclear",
      "sponsorship_evidence": "...",
      "search_relevance_reason": "..."
    }}
  ],
  "search_notes": []
}}
"""

    raw = (
        _grounded_gemini(
            prompt
        )
    )

    parsed = (
        _extract_json(
            raw
        )
    )

    return (
        JobSearchResponse.model_validate(
            parsed
        )
    )


# =========================================================
# CANONICAL URL ENFORCEMENT
# =========================================================


def _enforce_canonical_url(
    parsed: dict,
    original_job: JobRecord,
) -> dict:
    """
    Python safety gate after Gemini verification.

    verified_active is NOT allowed unless:

    1. Gemini identifies a specific canonical job URL
    2. Python confirms it looks like a specific posting
    3. It does not redirect to a generic careers/job board

    This prevents generic company boards from being
    presented as verified active job URLs.
    """

    status = (
        parsed.get(
            "verification_status",
            "verification_failed",
        )
    )

    if status != "verified_active":
        return parsed

    canonical_url = (
        str(
            parsed.get(
                "canonical_job_url",
                "",
            )
        )
        .strip()
    )

    notes = list(
        parsed.get(
            "verification_notes",
            []
        )
        or []
    )

    # -----------------------------------------------------
    # Missing canonical URL
    # -----------------------------------------------------

    if not canonical_url:
        parsed[
            "verification_status"
        ] = "verification_failed"

        parsed[
            "status_evidence"
        ] = (
            "The role may exist, but CareerScout "
            "could not identify the exact canonical "
            "job posting URL."
        )

        notes.append(
            "verified_active requires a specific "
            "canonical job URL."
        )

        parsed[
            "verification_notes"
        ] = notes

        return parsed

    # -----------------------------------------------------
    # Gemini returned generic URL
    # -----------------------------------------------------

    if not _looks_like_specific_job_url(
        canonical_url
    ):
        parsed[
            "verification_status"
        ] = "verification_failed"

        parsed[
            "status_evidence"
        ] = (
            "Current evidence suggests the role may "
            "exist, but the verifier returned only "
            "a generic company careers or ATS board "
            "instead of the exact job posting."
        )

        notes.append(
            "Generic job-board URLs cannot be "
            "classified as verified_active."
        )

        parsed[
            "verification_notes"
        ] = notes

        return parsed

    # -----------------------------------------------------
    # Python independently checks canonical URL
    # -----------------------------------------------------

    print(
        f"[Canonical URL Check] Started: "
        f"{canonical_url}",
        flush=True,
    )

    canonical_start = time.perf_counter()

    canonical_check = (
        _check_job_url(
            canonical_url
        )
    )

    canonical_time = (
        time.perf_counter()
        - canonical_start
    )

    print(
        f"[Canonical URL Check] "
        f"Finished in {canonical_time:.2f}s",
        flush=True,
    )

    parsed[
        "url_page_responded"
    ] = canonical_check[
        "page_responded"
    ]

    parsed[
        "http_status"
    ] = canonical_check[
        "http_status"
    ]

    # -----------------------------------------------------
    # Exact URL did not respond
    # -----------------------------------------------------

    if not canonical_check[
        "page_responded"
    ]:
        parsed[
            "verification_status"
        ] = "verification_failed"

        parsed[
            "status_evidence"
        ] = (
            "A specific canonical URL was identified, "
            "but CareerScout could not successfully "
            "reach that URL."
        )

        notes.append(
            canonical_check.get(
                "error"
            )
            or "Canonical URL could not be reached."
        )

        parsed[
            "verification_notes"
        ] = notes

        return parsed

    # -----------------------------------------------------
    # Exact posting returned 404/410
    # -----------------------------------------------------

    if canonical_check[
        "http_status"
    ] in {
        "404",
        "410",
    }:
        parsed[
            "verification_status"
        ] = "verified_closed"

        parsed[
            "status_evidence"
        ] = (
            "The exact canonical job posting "
            f"returned HTTP "
            f"{canonical_check['http_status']}."
        )

        notes.append(
            "The canonical specific posting appears "
            "to have been removed."
        )

        parsed[
            "verification_notes"
        ] = notes

        return parsed

    # -----------------------------------------------------
    # Exact URL redirected somewhere.
    #
    # Final URL must STILL be job specific.
    # -----------------------------------------------------

    final_url = (
        canonical_check.get(
            "final_url"
        )
        or canonical_url
    )

    if not _looks_like_specific_job_url(
        final_url
    ):
        parsed[
            "verification_status"
        ] = "verification_failed"

        parsed[
            "canonical_job_url"
        ] = final_url

        parsed[
            "status_evidence"
        ] = (
            "The specific posting URL redirected to "
            "a generic careers or ATS board, so the "
            "job cannot be confirmed as currently active."
        )

        notes.append(
            "verified_active requires the final "
            "canonical destination to remain "
            "job-specific."
        )

        parsed[
            "verification_notes"
        ] = notes

        return parsed

    # -----------------------------------------------------
    # Canonical URL passed Python gate.
    # -----------------------------------------------------

    parsed[
        "canonical_job_url"
    ] = final_url

    notes.append(
        "Python confirmed that the canonical URL "
        "is a specific job-posting URL."
    )

    parsed[
        "verification_notes"
    ] = notes

    return parsed


# =========================================================
# GROUNDED VERIFICATION
# =========================================================


def _grounded_verify_job(
    job: JobRecord,
    url_check: dict,
) -> JobVerificationResponse:

    prompt = f"""
You are CareerScout's independent job verification engine.

TODAY:
{date.today().isoformat()}


==================================================
DISCOVERED JOB
==================================================

Title:
{job.job_title}

Company:
{job.company}

Location:
{job.location}

Discovery URL:
{job.job_url}


==================================================
MANDATORY PYTHON URL CHECK
==================================================

{json.dumps(url_check, indent=2)}


Use Google Search to independently verify
this SPECIFIC job opening.


==================================================
IMPORTANT DISTINCTION
==================================================

A generic company career page is NOT a canonical
job posting.

Examples of GENERIC pages:

https://company.com/careers

https://jobs.ashbyhq.com/company

https://job-boards.greenhouse.io/company


Examples of SPECIFIC job postings:

https://jobs.ashbyhq.com/company/<job-id>

https://job-boards.greenhouse.io/company/jobs/<job-id>

https://jobs.lever.co/company/<job-id>


If the discovery URL is generic:

YOU MUST search for the exact individual job
posting before returning verified_active.


==================================================
VERIFIED ACTIVE
==================================================

Return verified_active ONLY when ALL are true:

1. The exact title/company can be established.

2. Positive current evidence shows applications
   are currently being accepted.

3. You identify the canonical DIRECT URL for this
   exact individual job.

4. canonical_job_url is NOT:

   - company homepage
   - careers homepage
   - generic ATS company board
   - search-results page


Positive evidence may include:

- active Apply action on exact posting
- official ATS exact posting currently available
- future application deadline
- explicit employer statement that exact role is open


HTTP 200 alone is NOT enough.


==================================================
VERIFIED CLOSED
==================================================

Return verified_closed only with reliable evidence:

- exact posting says closed
- position filled
- no longer accepting
- deadline passed
- archived
- exact posting removed with supporting evidence


==================================================
VERIFICATION FAILED
==================================================

Return verification_failed when:

- only a generic company/ATS board can be found
- exact canonical posting cannot be located
- current status cannot be established
- evidence conflicts
- information is stale
- exact title/company cannot be confirmed


IMPORTANT:

Seeing a title somewhere on a company's jobs board
is NOT enough for verified_active if you cannot
identify its exact direct posting URL.


==================================================
SOURCE FIDELITY
==================================================

The verified values are authoritative.

Return the exact verified:

- title
- company
- location
- canonical specific job URL
- requirements


If discovery gave an inaccurate title,
correct it.

Do not preserve an incorrect discovery title.


==================================================
WORK AUTHORIZATION
==================================================

Never infer visa compatibility.

sponsorship_status must be exactly:

explicitly_supported
explicitly_not_supported
unclear


==================================================
OUTPUT
==================================================

Return ONLY JSON:

{{
  "verification_status": "verified_active | verified_closed | verification_failed",
  "verification_method": "grounded_gemini",
  "grounded_search_used": true,
  "url_check_performed": true,
  "canonical_job_url": "...",
  "verified_title": "...",
  "verified_company": "...",
  "verified_location": "...",
  "url_page_responded": true,
  "http_status": "...",
  "status_evidence": "...",
  "experience_requirement": "...",
  "education_requirement": "...",
  "work_authorization_requirement": "...",
  "sponsorship_status": "explicitly_supported | explicitly_not_supported | unclear",
  "sponsorship_evidence": "...",
  "verification_notes": []
}}
"""

    print(
        "[Grounded Gemini + Google Search] Started",
        flush=True,
    )

    gemini_start = time.perf_counter()

    raw = (
        _grounded_gemini(
            prompt
        )
    )

    gemini_time = (
        time.perf_counter()
        - gemini_start
    )

    print(
        f"[Grounded Gemini + Google Search] "
        f"Finished in {gemini_time:.2f}s",
        flush=True,
    )

    parsed = (
        _extract_json(
            raw
        )
    )

    # -----------------------------------------------------
    # Python owns these facts initially.
    # -----------------------------------------------------

    parsed[
        "verification_method"
    ] = "grounded_gemini"

    parsed[
        "grounded_search_used"
    ] = True

    parsed[
        "url_check_performed"
    ] = True

    # -----------------------------------------------------
    # CRITICAL:
    #
    # Python now checks whatever canonical URL Gemini
    # claims before verified_active is allowed.
    # -----------------------------------------------------

    parsed = (
        _enforce_canonical_url(
            parsed,
            job,
        )
    )

    # -----------------------------------------------------
    # If canonical enforcement did not replace these,
    # preserve original deterministic values.
    # -----------------------------------------------------

    if (
        "url_page_responded"
        not in parsed
    ):
        parsed[
            "url_page_responded"
        ] = url_check[
            "page_responded"
        ]

    if (
        "http_status"
        not in parsed
    ):
        parsed[
            "http_status"
        ] = url_check[
            "http_status"
        ]

    return (
        JobVerificationResponse.model_validate(
            parsed
        )
    )


# =========================================================
# INTERNAL VERIFICATION PIPELINE
# =========================================================


def _verify_discovered_job(
    job: JobRecord,
) -> JobVerificationResponse:
    """
    Mandatory order:

    1. Python checks discovery URL
    2. Cheap deterministic verification
    3. Grounded verification when needed
    4. Canonical URL enforced before active status
    """

    verification_start = time.perf_counter()

    print(
        f"[Verification] Started for {job.job_title}",
        flush=True,
    )

    # ---------------------------------------------------------
    # INITIAL URL CHECK
    # ---------------------------------------------------------

    initial_url_start = time.perf_counter()

    url_check = (
        _check_job_url(
            job.job_url
        )
    )

    initial_url_time = (
        time.perf_counter()
        - initial_url_start
    )

    print(
        f"[Initial URL Check] "
        f"{initial_url_time:.2f}s",
        flush=True,
    )

    # ---------------------------------------------------------
    # CHEAP VERIFICATION
    # ---------------------------------------------------------

    cheap_start = time.perf_counter()

    cheap_result = (
        _cheap_page_verdict(
            job,
            url_check,
        )
    )

    cheap_time = (
        time.perf_counter()
        - cheap_start
    )

    print(
        f"[Cheap Verification] "
        f"{cheap_time:.2f}s",
        flush=True,
    )

    if cheap_result is not None:
        total_time = (
            time.perf_counter()
            - verification_start
        )

        print(
            f"[Verification] Finished deterministically "
            f"in {total_time:.2f}s",
            flush=True,
        )

        return cheap_result

    # ---------------------------------------------------------
    # GROUNDED VERIFICATION
    # ---------------------------------------------------------

    try:
        grounded_start = time.perf_counter()

        verification = (
            _grounded_verify_job(
                job,
                url_check,
            )
        )

        grounded_time = (
            time.perf_counter()
            - grounded_start
        )

        total_time = (
            time.perf_counter()
            - verification_start
        )

        print(
            f"[Grounded Verification Pipeline] "
            f"{grounded_time:.2f}s",
            flush=True,
        )

        print(
            f"[Verification Total] "
            f"{total_time:.2f}s",
            flush=True,
        )

        return verification

    except Exception as exc:
        return JobVerificationResponse(
            verification_status=(
                "verification_failed"
            ),
            verification_method=(
                "pipeline_failure"
            ),
            grounded_search_used=True,
            url_check_performed=True,
            canonical_job_url=(
                url_check.get(
                    "final_url",
                    job.job_url,
                )
            ),
            verified_title=(
                job.job_title
            ),
            verified_company=(
                job.company
            ),
            verified_location=(
                job.location
            ),
            url_page_responded=(
                url_check[
                    "page_responded"
                ]
            ),
            http_status=(
                url_check[
                    "http_status"
                ]
            ),
            status_evidence=(
                "Verification pipeline failed "
                "before trustworthy current status "
                "could be established."
            ),
            experience_requirement=(
                job.experience_requirement
            ),
            education_requirement=(
                job.education_requirement
            ),
            work_authorization_requirement=(
                job.work_authorization_requirement
            ),
            sponsorship_status=(
                job.sponsorship_status
            ),
            sponsorship_evidence=(
                job.sponsorship_evidence
            ),
            verification_notes=[
                str(exc)
            ],
        )


# =========================================================
# VERIFIED RECORD NORMALIZATION
# =========================================================


def _apply_verified_truth(
    job: JobRecord,
    verification: JobVerificationResponse,
) -> JobRecord:
    """
    For successfully verified active/closed jobs,
    replace discovery fields with verified fields.

    This prevents the root agent from accidentally
    showing the old generic discovery URL.

    Example:

    Discovery:
    jobs.ashbyhq.com/mintlify

    Verification:
    jobs.ashbyhq.com/Mintlify/<exact-id>

    Final stored/display record gets the exact URL.
    """

    if (
        verification.verification_status
        not in {
            "verified_active",
            "verified_closed",
        }
    ):
        return job

    updates = {}

    if (
        verification.verified_title
        and verification.verified_title.lower()
        != "unknown"
    ):
        updates[
            "job_title"
        ] = (
            verification.verified_title
        )

    if (
        verification.verified_company
        and verification.verified_company.lower()
        != "unknown"
    ):
        updates[
            "company"
        ] = (
            verification.verified_company
        )

    if (
        verification.verified_location
        and verification.verified_location.lower()
        != "unknown"
    ):
        updates[
            "location"
        ] = (
            verification.verified_location
        )

    if (
        verification.canonical_job_url
        and verification.canonical_job_url.lower()
        != "unknown"
    ):
        updates[
            "job_url"
        ] = (
            verification.canonical_job_url
        )

    if (
        verification.experience_requirement
        and verification.experience_requirement.lower()
        != "unknown"
    ):
        updates[
            "experience_requirement"
        ] = (
            verification.experience_requirement
        )

    if (
        verification.education_requirement
        and verification.education_requirement.lower()
        != "unknown"
    ):
        updates[
            "education_requirement"
        ] = (
            verification.education_requirement
        )

    if (
        verification.work_authorization_requirement
        and verification.work_authorization_requirement.lower()
        != "unknown"
    ):
        updates[
            "work_authorization_requirement"
        ] = (
            verification.work_authorization_requirement
        )

    updates[
        "sponsorship_status"
    ] = (
        verification.sponsorship_status
    )

    updates[
        "sponsorship_evidence"
    ] = (
        verification.sponsorship_evidence
    )

    return job.model_copy(
        update=updates
    )


# =========================================================
# ONE PUBLIC JOB TOOL
# =========================================================


def search_and_verify_jobs(
    role_query: str = "",
    location: str = "",
    experience_level: str = "unknown",
    work_authorization: str = "unknown",
    max_results: int = 5,
    job_url: str = "",
    job_title: str = "",
    company: str = "",
) -> dict:
    """
    CareerScout's single public job tool.

    MODE 1:
    Discover multiple jobs and verify all of them.

    MODE 2:
    Verify one supplied job URL.
    """

    # =====================================================
    # MODE 2:
    # SINGLE JOB VERIFICATION
    # =====================================================

    if job_url.strip():

        supplied_job = JobRecord(
            job_title=(
                job_title.strip()
                or "unknown"
            ),
            company=(
                company.strip()
                or "unknown"
            ),
            location="unknown",
            workplace_type="unknown",
            source_name="user_supplied",
            source_type="other",
            job_url=job_url.strip(),
            posting_date="unknown",
            experience_requirement="unknown",
            education_requirement="unknown",
            work_authorization_requirement=(
                "unknown"
            ),
            sponsorship_status="unclear",
            sponsorship_evidence="unknown",
            search_relevance_reason=(
                "User supplied a specific "
                "job for verification."
            ),
        )

        verification = (
            _verify_discovered_job(
                supplied_job
            )
        )

        final_job = (
            _apply_verified_truth(
                supplied_job,
                verification,
            )
        )

        result = VerifiedJobResult(
            discovered_job=(
                final_job
            ),
            verification=(
                verification
            ),
        )

        active = []
        closed = []
        failed = []

        if (
            verification.verification_status
            == "verified_active"
        ):
            active.append(
                result
            )

        elif (
            verification.verification_status
            == "verified_closed"
        ):
            closed.append(
                result
            )

        else:
            failed.append(
                result
            )

        response = SearchAndVerifyResponse(
            mode=(
                "single_job_verification"
            ),
            verified_active=(
                active
            ),
            verified_closed=(
                closed
            ),
            verification_failed=(
                failed
            ),
            stats={
                "discovered": 0,
                "jobs_processed": 1,
                "verified_active": len(
                    active
                ),
                "verified_closed": len(
                    closed
                ),
                "verification_failed": len(
                    failed
                ),
                "deterministic_verifications": (
                    1
                    if verification.verification_method
                    == "deterministic_page"
                    else 0
                ),
                "grounded_verifications": (
                    1
                    if verification.verification_method
                    == "grounded_gemini"
                    else 0
                ),
            },
            search_notes=[
                (
                    "Discovery was skipped because "
                    "a specific job URL was supplied."
                )
            ],
        )

        return response.model_dump()

    # =====================================================
    # MODE 1:
    # DISCOVER + VERIFY
    # =====================================================

    if not role_query.strip():
        return {
            "mode": "job_discovery",
            "verified_active": [],
            "verified_closed": [],
            "verification_failed": [],
            "stats": {
                "discovered": 0,
                "jobs_processed": 0,
                "verified_active": 0,
                "verified_closed": 0,
                "verification_failed": 0,
                "deterministic_verifications": 0,
                "grounded_verifications": 0,
            },
            "search_notes": [
                (
                    "A role query is required "
                    "when no job URL is supplied."
                )
            ],
        }

    pipeline_start = time.perf_counter()

    print(
        "\n[CareerScout] Job discovery started",
        flush=True,
    )

    try:
        discovery_start = time.perf_counter()

        discovered = (
            _search_jobs_internal(
                role_query=(
                    role_query
                ),
                location=(
                    location
                    or "unknown"
                ),
                experience_level=(
                    experience_level
                ),
                work_authorization=(
                    work_authorization
                ),
                max_results=(
                    max_results
                ),
            )
        )

        discovery_time = (
            time.perf_counter()
            - discovery_start
        )

        print(
            f"[Discovery] Finished in "
            f"{discovery_time:.2f}s",
            flush=True,
        )

    except Exception as exc:
        return {
            "mode": "job_discovery",
            "verified_active": [],
            "verified_closed": [],
            "verification_failed": [],
            "stats": {
                "discovered": 0,
                "jobs_processed": 0,
                "verified_active": 0,
                "verified_closed": 0,
                "verification_failed": 0,
                "deterministic_verifications": 0,
                "grounded_verifications": 0,
            },
            "search_notes": [
                (
                    "Live discovery failed. "
                    "No conclusion should be made "
                    "about current job availability."
                ),
                str(exc),
            ],
        }

    active_results = []
    closed_results = []
    failed_results = []

    deterministic_count = 0
    grounded_count = 0

    # =====================================================
    # VERIFY EVERY DISCOVERED JOB
    # =====================================================

    for index, job in enumerate(
        discovered.jobs,
        start=1,
    ):

        print(
            f"\n[Discovered Job {index}] "
            f"{job.job_title} — {job.company}",
            flush=True,
        )

        print(
            f"[Discovered URL] "
            f"{job.job_url}",
            flush=True,
        )

        verification = (
            _verify_discovered_job(
                job
            )
        )

        # -------------------------------------------------
        # IMPORTANT
        #
        # Replace generic discovery fields with
        # canonical verified truth when successful.
        # -------------------------------------------------

        final_job = (
            _apply_verified_truth(
                job,
                verification,
            )
        )

        result = VerifiedJobResult(
            discovered_job=(
                final_job
            ),
            verification=(
                verification
            ),
        )

        if (
            verification.verification_method
            == "deterministic_page"
        ):
            deterministic_count += 1

        elif (
            verification.verification_method
            == "grounded_gemini"
        ):
            grounded_count += 1

        if (
            verification.verification_status
            == "verified_active"
        ):
            active_results.append(
                result
            )

        elif (
            verification.verification_status
            == "verified_closed"
        ):
            closed_results.append(
                result
            )

        else:
            failed_results.append(
                result
            )

    pipeline_time = (
        time.perf_counter()
        - pipeline_start
    )

    print(
        f"\n[CareerScout] Total discovery + verification "
        f"time: {pipeline_time:.2f}s",
        flush=True,
    )

    response = SearchAndVerifyResponse(
        mode="job_discovery",
        verified_active=(
            active_results
        ),
        verified_closed=(
            closed_results
        ),
        verification_failed=(
            failed_results
        ),
        stats={
            "discovered": len(
                discovered.jobs
            ),
            "jobs_processed": len(
                discovered.jobs
            ),
            "verified_active": len(
                active_results
            ),
            "verified_closed": len(
                closed_results
            ),
            "verification_failed": len(
                failed_results
            ),
            "deterministic_verifications": (
                deterministic_count
            ),
            "grounded_verifications": (
                grounded_count
            ),
        },
        search_notes=(
            discovered.search_notes
        ),
    )

    return response.model_dump()


# =========================================================
# ROOT CAREERSCOUT AGENT
# =========================================================


root_agent = Agent(
    name="careerscout_agent",
    model=MODEL,
    description=(
        "CareerScout discovers and verifies current "
        "job opportunities for early-career candidates."
    ),
    instruction="""
You are CareerScout.


==================================================
ONE JOB TOOL
==================================================

You have ONE public job tool:

search_and_verify_jobs


Use it for BOTH:

- discovering jobs
- verifying one supplied job


==================================================
WHEN USER ASKS TO FIND JOBS
==================================================

Call search_and_verify_jobs with:

- role_query
- location
- experience_level when provided
- work_authorization only when explicitly provided
- max_results when provided

Do not supply job_url.

The Python tool automatically:

1. discovers jobs
2. checks every source URL
3. resolves exact canonical posting URLs when needed
4. verifies every job
5. categorizes active / closed / failed


==================================================
WHEN USER ASKS TO VERIFY ONE JOB
==================================================

Use the SAME search_and_verify_jobs tool.

Supply:

- job_url
- job_title if known
- company if known

When job_url exists, discovery is automatically skipped.


==================================================
CANONICAL URL RULE
==================================================

A verified_active result MUST have an exact
individual job-posting URL.

Generic URLs are NOT acceptable final links.

Examples of generic links:

- company.com/careers
- jobs.ashbyhq.com/company
- job-boards.greenhouse.io/company

Do not present those as verified_active job links.


For verified jobs:

ALWAYS display:

verification.canonical_job_url

or the normalized discovered_job.job_url,
which has already been replaced by verified
canonical truth.


Never prefer the original generic discovery URL.


==================================================
VERIFIED SOURCE FIDELITY
==================================================

For verified jobs, prefer verified values over
discovery values:

- verified title
- verified company
- verified location
- canonical URL
- verified requirements

Do not preserve an inaccurate discovery title.


==================================================
RESUME UNDERSTANDING
==================================================

When resume content is provided:

- use only evidence actually present
- never invent candidate information
- never convert project work into employment
- distinguish projects from professional experience


==================================================
SEARCH FAILURE
==================================================

If discovery fails:

- report the failure
- do not invent jobs
- do not generate jobs from model memory
- do not summarize the resume unnecessarily
- do not treat zero returned jobs as proof that
  no jobs exist


==================================================
PRESENTATION
==================================================

Show:

1. verified_active
2. verified_closed
3. verification_failed

Do not hide closed or failed results.

verification_failed means CareerScout could not
establish trustworthy current status.

It does not automatically mean a job is fake.


==================================================
NOT IMPLEMENTED YET
==================================================

Do NOT yet:

- calculate candidate match scores
- classify Recommended / Stretch / Weak / Mismatch
- decide Apply / Skip


==================================================
WORK AUTHORIZATION
==================================================

Do not provide immigration advice.

Do not infer visa compatibility.

Use only explicit employer/source evidence.


==================================================
ARCHITECTURE PRINCIPLE
==================================================

One public job capability.

Python controls mandatory execution and
canonical URL enforcement.

Gemini handles interpretation and search reasoning.
""",
    tools=[
        search_and_verify_jobs,
    ],
)