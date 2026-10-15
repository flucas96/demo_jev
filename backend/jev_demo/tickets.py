"""Twenty fictional Jira tickets for a varied, repeatable triage queue."""

from .batch_models import JiraTicket
from .catalog import SCENARIOS


def _ticket(ticket_id: str, title: str, tag: str, description: str) -> JiraTicket:
    """Build a sample whose full text includes its Jira identifier and summary."""
    return JiraTicket(
        id=ticket_id,
        title=title,
        tag=tag,
        text=f"Jira: {ticket_id}\nSummary: {title}\n\n{description}",
    )


TICKETS: list[JiraTicket] = [
    JiraTicket(id=ticket_id, title=example.title, text=example.text, tag=example.tag)
    for ticket_id, example in zip(
        ("INC-2041", "SUP-1863", "BUG-2098", "BUG-2110", "SUP-1902"),
        SCENARIOS["triage"].examples,
        strict=True,
    )
] + [
    _ticket(
        "BUG-2121",
        "Save button falls below the mobile viewport",
        "Mobile layout",
        "On the production workspace-settings page in mobile Safari, opening the "
        "keyboard covers the Save button and the form does not scroll. Four users "
        "reproduced it at a 390-pixel viewport. The same update succeeds on desktop, "
        "and the settings API returns 200. Affected users can save from a desktop browser.",
    ),
    _ticket(
        "SUP-1913",
        "Where can we download last month's invoice?",
        "How-to question",
        "A workspace billing administrator asks where to download the previous month's "
        "paid invoice. They can sign in and open Settings, but have not tried the Billing "
        "tab. No error or incorrect charge is reported. Their production workspace is "
        "working normally; they need the document for their monthly accounting close.",
    ),
    _ticket(
        "BUG-2124",
        "API tokens expire immediately after creation",
        "Token expiry",
        "Since 10:05 UTC, freshly created API tokens in one production workspace return "
        "401 token_expired on every request. Their expiry timestamps are set one hour "
        "before creation. Existing tokens still work, and two integrations can continue "
        "using those tokens. New integrations cannot be connected. The gateway passes "
        "the requests through; the token-validation service emits the rejection.",
    ),
    _ticket(
        "INC-2052",
        "Staging deployment has no healthy pods",
        "Staging only",
        "The staging search service returns 503 after today's container image update. "
        "All staging pods fail their readiness probe with a missing configuration key. "
        "This blocks the release team's staging checks. Production runs the previous "
        "image, all production health checks pass, and no customers are affected. "
        "Reverting the staging image is available as a workaround.",
    ),
    _ticket(
        "BUG-2127",
        "Keyboard users cannot open the project menu",
        "Accessibility",
        "In the production web app, pressing Enter or Space on the focused project-menu "
        "button does nothing. Clicking it with a mouse works; project requests succeed. "
        "This reproduces in Chrome and Firefox and blocks keyboard-only users from "
        "switching projects through the menu. They can navigate using a saved direct "
        "project URL. No failed backend request appears in the browser trace.",
    ),
    _ticket(
        "SUP-1920",
        "Seat count on renewal does not match the contract",
        "Renewal question",
        "A production workspace renewed for 80 seats, but its signed amendment lists "
        "60 seats from the renewal date. The administrator attached the amendment "
        "reference and invoice number. Please reconcile the subscription quantity and "
        "adjust the invoice if needed. All 58 active members can use the product and "
        "no access has been removed. The billing page renders the invoiced count correctly.",
    ),
    _ticket(
        "INC-2058",
        "EU file uploads fail with exhausted storage capacity",
        "Regional interruption",
        "Production file uploads in the EU region have failed continuously since "
        "11:20 UTC with HTTP 507. Storage telemetry shows the write volume at capacity. "
        "Downloads and the US region remain healthy, but no EU workspace can upload "
        "files and there is no customer workaround. No data loss is reported. "
        "The upload workers are running and their logs identify storage allocation failures.",
    ),
    _ticket(
        "DOC-402",
        "Webhook guide omits the retry schedule",
        "Documentation gap",
        "The public webhook guide says failed deliveries are retried but does not list "
        "the delay or maximum attempt count. A developer requests these details to plan "
        "their receiver's monitoring. Their production webhook endpoint receives events "
        "successfully and no failed delivery is reported. This request concerns the "
        "documentation wording, with no product behavior change requested.",
    ),
    _ticket(
        "BUG-2136",
        "Viewer role can still open the admin screen",
        "Permission change",
        "After an administrator downgraded a user to Viewer in a production workspace, "
        "that user's existing session could still read the admin-members endpoint with "
        "HTTP 200. A fresh session correctly gets 403. The issue reproduces through a "
        "direct API request, so hiding the navigation item would not resolve it. "
        "Revoking the old session removes access. No unauthorized modification is reported.",
    ),
    _ticket(
        "BUG-2140",
        "Dashboard looks wrong after changing timezone",
        "Unclear source",
        "One customer says the production dashboard shows yesterday's totals after "
        "switching their workspace timezone. A refresh sometimes fixes it. We have "
        "not captured the API response or compared the reporting job's timezone with "
        "the browser value. Their CSV export shows the expected total and is usable "
        "for now. It is unclear whether the stale value starts in the report or its display.",
    ),
    _ticket(
        "INC-2062",
        "Follow-up for yesterday's gateway interruption",
        "Resolved incident",
        "Yesterday's production gateway incident ended at 16:42 UTC after a route "
        "configuration rollback. All synthetic checks and customer requests have been "
        "healthy for 18 hours. This ticket requests a post-incident review of why the "
        "deployment validation missed the invalid route. There is no current outage "
        "and no ongoing customer impairment. The original incident is marked resolved.",
    ),
    _ticket(
        "BUG-2145",
        "Filter badge count is off by one",
        "Cosmetic mismatch",
        "The production issues page displays a badge of three active filters when two "
        "filters are selected. The result set and URL contain the correct two filters. "
        "Clearing filters and selecting them again reproduces the badge issue in Chrome. "
        "Users can continue searching and exporting the correct results; this is a "
        "display-only count mismatch with no lost or hidden records observed.",
    ),
    _ticket(
        "SUP-1938",
        "Can workspace exports include an extra CSV column?",
        "Feature request",
        "A customer requests the project cost-center field as an optional column in "
        "scheduled CSV exports. The current export matches the documented schema and "
        "completes successfully in production. They join the cost-center value from "
        "their own lookup table today. This is a request for a future reporting feature, "
        "with no regression, access failure, or service interruption reported.",
    ),
    _ticket(
        "SUP-1941",
        "Urgent: report failed, details to follow",
        "Incomplete report",
        "A support message says only: 'The report failed again. This is urgent.' "
        "The intake form has no report name, timestamp, workspace, environment, error "
        "text, or number of affected users. No screenshot or service telemetry was "
        "provided. Support has requested reproduction details. Neither the scope "
        "of impact nor the availability of a workaround is established.",
    ),
    _ticket(
        "BUG-2152",
        "Invoice download spins despite a successful response",
        "Download interaction",
        "In production Firefox, clicking Download invoice leaves a loading spinner "
        "and never saves a file. The invoice endpoint returns HTTP 200 with a valid PDF; "
        "opening that response URL directly downloads it. The browser console reports "
        "an exception in the download-button handler. Chrome works, payment amounts "
        "are correct, and affected users can use the direct download link as a workaround.",
    ),
]
