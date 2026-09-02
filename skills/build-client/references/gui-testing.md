# Direct VMware GUI testing

Use this contract whenever the selected test opens a window, tray icon, dialog,
desktop notification, or another graphical surface.

## Transport boundary

- Operate graphical programs only in the visible VMware Workstation console.
- Never use SSH, `nohup`, X forwarding, a synthetic `DISPLAY`, or a remote shell
  to launch the GUI process.
- Do not substitute Xvfb for a desktop, tray, focus, notification, or rendering
  test.
- If direct console interaction or visible VM identity cannot be verified, stop.

## Admission

Confirm the exact scenario, expected visible assertions, cleanup, and test record.
Validate the selected Profile, recipe, candidate, artifact hash, VMX identity,
queue, and prerequisites. Claim the shared queue and issue a fresh GUI receipt
before opening or changing the guest desktop.

If the VM is stopped, start it in GUI mode only for the explicitly requested GUI
test. If it is running, open the configured Workstation executable and selected
VMX without changing power state. Verify the configured display name and expected
guest desktop before every input. Capture the initial console and power state; do
not type a secret into an unverified window.

## Execute and judge

Use the private test plan for exact process names, working directory, launcher,
arguments, and cleanup. Keep the guest terminal visible when its diagnostics are
part of the evidence. Use graceful exact-name cleanup; hard kills and wildcard
process matching require separate exceptional authorization.

Judge visible, measurable outcomes such as expected window or dialog, text,
enabled state, navigation, tray menu, notification, rendering, and absence of
fatal terminal errors. A running PID or opened window alone is not a pass. SSH may
supplement evidence with read-only exact-process and executable readback after the
console launch, but must not start, restart, focus, or close the GUI process.

Capture final state and decisive screenshots, perform only test-owned cleanup,
restore the original power state with soft shutdown only if this test started the
VM, and release the queue last.
