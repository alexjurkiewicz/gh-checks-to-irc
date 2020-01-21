import json

from typing import TypedDict, Dict, List, Literal, Any, Optional
from enum import Enum


class Config(TypedDict):
    repos: List[int]
    branches: List[str]
    conclusions: List[str]
    watch_prs: bool
    sha_length: int
    message_template: str


config: Config = {
    "repos": [
        23038334,  # crawl/crawl
        33104844,  # XXX testing -- alexjurkiewicz/crawl-ref
    ],  # What repos do we care about?
    "branches": [
        "master",
        "github-actions",  # XXX testing
    ],  # When a commit on one of these branches fails, post a message
    "conclusions": [
        "failure",
        "action_required",
        "timed_out",
    ],  # What GitHub check suite conclusions should we post about?
    "watch_prs": True,  # Should we post messages when PRs fail?
    "sha_length": 8,  # How long should SHA snippets be?
    "message_template": "Build {conclusion} at {commit_desc} (by {committer}). Details: {commit_html_url}",
}


def debug(msg: str) -> None:
    print("DEBUG: " + msg)


class LambdaHTTPEvent(TypedDict):
    headers: Dict[str, str]
    multiValueHeaders: Dict[str, List[str]]
    httpMethod: str
    path: str
    body: str


class LambdaResponse(TypedDict):
    statusCode: int
    body: str


class GitHubWebhookPayloadRepository(TypedDict):
    id: int
    url: str
    name: str


class GitHubWebhookPayloadCommit(TypedDict):
    ref: str
    sha: str
    repo: GitHubWebhookPayloadRepository


class GitHubWebhookPayloadPullRequest(TypedDict):
    url: str
    id: int
    number: int
    head: GitHubWebhookPayloadCommit
    base: GitHubWebhookPayloadCommit


class GitHubWebhookPerson(TypedDict):
    login: str
    id: int
    html_url: str


class GithubWebhookCheckSuiteApp(TypedDict):
    id: int
    owner: GitHubWebhookPerson
    name: str


class GitHubCommitCommitter(TypedDict):
    name: str


class GitHubHeadCommit(TypedDict):
    committer: GitHubCommitCommitter


class GitHubWebhookPayloadCheckSuiteSection(TypedDict):
    head_branch: str
    head_sha: str
    status: Literal["requested", "in_progress", "completed"]
    conclusion: Literal[
        "success", "failure", "neutral", "cancelled", "timed_out", "action_required"
    ]
    url: str
    pull_requests: List[GitHubWebhookPayloadPullRequest]
    app: GithubWebhookCheckSuiteApp
    updated_at: str
    head_commit: GitHubHeadCommit


class GitHubWebhookPayloadRepositorySection(TypedDict):
    id: int
    name: str
    full_name: str
    html_url: str
    owner: GitHubWebhookPerson


class GitHubWebhookPayload(TypedDict):
    action: str
    check_suite: GitHubWebhookPayloadCheckSuiteSection
    repository: GitHubWebhookPayloadRepositorySection
    sender: Dict[str, Any]


def error(msg: str) -> LambdaResponse:
    return send_reply({"statusCode": 400, "body": msg})


def ok(msg: str) -> LambdaResponse:
    return send_reply({"statusCode": 200, "body": msg})


def send_reply(resp: LambdaResponse) -> LambdaResponse:
    debug(f"Sending reply: {resp}")
    return resp


def handler(event: LambdaHTTPEvent, context: Any) -> LambdaResponse:
    debug(f"Hello. Event: {event}")

    # First, validate we care about this webhook event
    event_type = event["headers"].get("X-GitHub-Event")
    if event_type is None:
        return error("Missing X-GitHub-Event header")
    if event_type != "check_suite":
        return ok("Ignored based on X-GitHub-Event value")

    try:
        body: GitHubWebhookPayload = json.loads(event["body"])
    except json.decoder.JSONDecodeError as e:
        return error(f"Couldn't parse body ({e})")

    if body["action"] != "completed":
        return ok("Ignored based on action != completed")

    check_suite = body["check_suite"]
    if check_suite["status"] != "completed":
        return ok("Ignored based on check_suite status != completed")

    conclusion = check_suite["conclusion"]
    if conclusion not in ("failure", "action_required", "timed_out"):
        return ok(
            "Ignored based on check_suite conclusion not in ('failure', 'action_required', 'timed_out')"
        )

    base_repo_id = body["repository"]["id"]
    matching_base_repo = base_repo_id in config["repos"]
    if not matching_base_repo:
        return ok(f"Ignored based on non-watched base repository ({base_repo_id})")

    # We care if either:
    # 1. watch-prs is true and there is a PR against a repo we watch,
    matching_pr: Optional[GitHubWebhookPayloadPullRequest] = None
    if config["watch_prs"] is True:
        debug(f"Looking for PRs in {config['repos']}")
        for pr in check_suite["pull_requests"]:
            if pr["base"]["repo"]["id"] in config["repos"]:
                debug(f"PR {pr} is a match")
                matching_pr = pr
                break
    # 2. or (assuming there's no interesting PR), the branch is an important one
    branch = check_suite["head_branch"]
    if not matching_pr:
        if branch not in config["branches"]:
            return ok(f"Ignored based on no matching PR/branch")
        debug(f"Alerting on branch {branch}")

    # Build the reponse vars
    owner_base_url = body["repository"]["owner"]["html_url"]
    repo_name = body["repository"]["name"]
    committer = check_suite["head_commit"]["committer"]["name"]
    if matching_pr:
        pr_num = matching_pr["number"]
        commit_desc = f"PR #{pr_num}"
        commit_html_url = (
            f"{owner_base_url}/{repo_name}/pull/{pr_num}#partial-pull-merging"
        )
    else:  # commit directly to a branch without an attached PR
        sha = check_suite["head_sha"][: config["sha_length"]]
        commit_desc = f"{sha} (branch {branch})"
        commit_html_url = f"{owner_base_url}/{repo_name}/commit/{sha}"

    message = config["message_template"].format(
        conclusion=conclusion,
        commit_desc=commit_desc,
        committer=committer,
        commit_html_url=commit_html_url,
    )
    debug("Message is: " + message)

    resp = {"message": "We cared about this message!"}
    return ok(json.dumps(resp))
