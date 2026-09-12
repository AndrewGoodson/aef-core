# ADR 0211: Prepare trusted inputs before isolating evaluation

Status: accepted during the September 2026 repository review.

## Reproduced failures

The stored loop-gate workflow and adoption template put the entire job in a
`python:3.13-slim` container with `--network none`. Checkout, package
installation and candidate fetch all followed that setting. An actual Docker
reproduction failed to obtain the missing build dependency during installation.
The workflow could not prepare a fresh runner for its claimed isolated gate.

The candidate branch was also interpolated directly into shell source. The
optional live-harness CI job had no event/ref condition separating ordinary PR
validation from a configured credentialed runner.

## Decision

Prepare dependencies from trusted main with network access, then evaluate in a
separate Docker invocation with networking disabled. Fetch the candidate as
quoted environment data. The evaluation repository must contain the required
Git objects without host credentials or hooks. Candidate evaluation gets the
installed trusted runtime, a read-only root and repository, an unprivileged
user, and only the explicitly writable temporary and loop-state locations.
It gets no Docker socket or host credential mount.

Use the same workflow renderer for the stored core workflow and the adoption
template so their isolation steps cannot drift independently. Installation
failures must stop preparation; a missing optional adopter package is distinct
from a package that exists and fails to install.

The configured live-harness job runs only on main pushes. This stops its normal
PR execution; it does not secure a self-hosted runner against a PR author who
changes workflow YAML. Credentialed runners still need access restrictions
outside that editable workflow. No runner settings or secrets were changed.
See GitHub's [runner access guidance](https://docs.github.com/en/actions/how-tos/manage-runners/self-hosted-runners/manage-access)
and [environment-variable guidance for shell inputs](https://docs.github.com/en/actions/reference/security/secure-use#use-an-intermediate-environment-variable).

## Compatibility and limits

Workflows remain opt-in and existing adopter workflows remain owner files.
Rerunning adoption does not replace them; review and apply the updated template
explicitly. Main remains the trusted base branch used by the shipped workflow.
Owners must configure their dependency source, corpus, entrypoint and build
command before using an adopter gate. Package installation is trusted setup,
not a sandbox for an untrusted dependency or main commit.

The network-isolation flag is still an attestation from the caller. Local
invocations must supply actual containment. Docker restrictions do not prove
complete isolation against kernel vulnerabilities, and persistent loop state
remains a writable output of evaluation. Evolution, Tier-1 merge and live-model
permission gates are unchanged. This review did not dispatch a live workflow
or call a model.

Validation and its limits are recorded in the
[repository review](../model-checks/2026-09-11-repository-review.md).
