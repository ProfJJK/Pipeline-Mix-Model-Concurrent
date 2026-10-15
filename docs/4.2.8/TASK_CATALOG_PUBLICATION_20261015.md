# Protected task-catalog publication

This source implementation connects the offline task matrix to the existing
Chapter 06 native runner and four shared admission seats. It does not run providers
when imported, grant a public activation endpoint, or update any delivered bundle.
The owner-run consolidated installer remains the only host execution boundary.

## Preparation and owner wrapper contract

1. `scripts/prepare_task_catalog_428.py` writes a fresh ordinary release directory
   containing a deterministic request and manifest. Supply the exact configuration,
   publisher-evidence catalog, executable paths/hashes/versions, source commit, and
   fresh request ID. It refuses an existing or redirected destination and Google
   Drive. It executes no provider. Include `--allow-partial-publication` for the
   owner's approved availability behavior; the source default is false.
2. The consolidated installer validates those pins, copies the request to a fresh
   protected Program Files root, and prepares its guarded SYSTEM runtime context.
   The active board must already have its protected routing journal initialized.
   Task planning remains disabled until this request is published. The wrapper
   owns singleton, resource monitoring, RAM setup, and process lifecycle.
3. Retain `protected_request(path, sha256, active_policy, active_task_catalog)`
   while calling `run_acceptance(runtime, request)`. The context requires SYSTEM,
   holds all ancestors and the file against replacement, checks protected ACLs,
   size, links, exact bytes, plan, and preceding authority. Directory handles
   include FILE_LIST_DIRECTORY; metadata-only READ_CONTROL cannot enforce delete
   sharing. No model output or client-supplied flag grants this authority.
4. The runtime supplies `config`, `store`, its existing `admission` and `ramdisk`,
   `stop_event`, trusted `boot_id`, a fresh 32-hex `catalog_containment_id`, and the
   current critical resource action. Probes are sequential through `NativeRunner`.
   They use the same joint native/Docker budget, route holds, account ownership,
   cleanup fences and retained Agy agent paths as production. No second pool or
   capacity override is created. `WAITING_ADMISSION` permits the wrapper's bounded
   unattended wait and another call with the same request, without repeating any
   completed probe or prompting the owner. A failed/unknown earlier attempt holds.
5. Successful results atomically publish the accepted catalog and consume durable
   evidence in the board transaction. `catalog_published` describes that action;
   it does not prove every task type/tier is usable. Save the returned sanitized
   per-row coverage with the owner report. It includes native accepted choices,
   current model/provider/pool holds, eligible choices, and different-family
   review availability; tier 10 review requires maximum effort. Research, input
   context and human SRS approval still depend on each task.
6. After committed publication, encode the exact returned catalog and create a
   new protected catalog file. In a new coherent board transaction call
   `enabled_candidate(conn, request, raw_configuration, catalog_path=...,`
   `catalog_bytes=...)`. It returns a copy enabling `catalog_activation` and a
   hash-pinned `task_planning` configuration only if the active request, routing,
   four slots, provider contracts, six worker profiles, and agent pins still
   match. Write it to a **new** private candidate configuration. Validate that
   candidate with the normal protected loader before selecting it at cutover.
   A file-write/cutover failure preserves the committed journal and previous
   configuration; it never rolls back evidence or silently overwrites old files.

## Evidence and availability semantics

Every selected profile, including one present in an older tier catalog, needs
fresh proof for this exact executable. The native receipt binds requested and
reported model/effort, production inference policy, binary hash/version, owned
Windows process identity, worker account, output hash, attempt and reservation
fence. The provider specification, all six isolated identities and Agy agent
contract are also pinned. Physical cleanup must succeed before the shared seat
is released. Unknown cleanup retains occupancy and prevents publication.

With explicit partial publication, actual typed quota, busy or provider failures
remain `AVAILABILITY_WAIT`; they create the existing scoped Chapter 06 cooldown.
Subsequent targets already covered by a live hold are separately recorded as
`AVAILABILITY_WAIT_UNTESTED`. Those records contain the exact controller hold
snapshot and explicitly state that no native probe ran. They have no invented
native receipt or reservation and never become accepted choices. Expired,
changed, authentication, configuration or compatibility holds cannot masquerade
as these temporary availability records. A different prepared request is needed
to add a previously unaccepted target after later native acceptance.

The five ranked alternatives, scores, costs and reasoning floors remain intact.
Only real native successes enter executable choices. At least one usable route
must exist; empty coverage cannot publish. Missing higher-tier/different-family
review remains a visible coverage hold. Published immutable job captures remain
unchanged, and current retirement/capacity rules still govern new starts.

## Verified boundary

Source tests use temporary SQLite boards, fake native receipts, injected runner
and RAM adapters, and a subprocess prohibition. They exercise publication CAS,
rollback/replay, shared reservations, exact binary/effort/worker evidence, scoped
quota deferral, five-option preservation, cleanup quarantine, configuration
binding and fresh release preparation. They do not attest installed selectors,
SYSTEM ACL behavior, deployment, or useful-job completion. Actual host route
coverage is unknown until the owner-run acceptance report is produced.
