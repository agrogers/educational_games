/**
 * Live realtime games — standalone page bootstrap.
 *
 * Reads the mount target from the page template and mounts the right
 * component.  The host page passes a session id; the play page may pass a
 * pre-filled game code.
 */

import { mount, whenReady } from "@odoo/owl";
import { makeEnv, startServices } from "@web/env";
import { LiveGameHost } from "./host_console";
import { LiveGamePlayer } from "./student_player";

async function boot() {
    await whenReady();
    const root = document.getElementById("lg-root");
    if (!root) {
        return;
    }
    const env = await makeEnv();
    await startServices(env);
    const props = {};
    if (root.dataset.kind === "host") {
        props.sessionId = Number(root.dataset.sessionId);
        mount(LiveGameHost, root, { env, props });
    } else if (root.dataset.kind === "play") {
        props.defaultCode = root.dataset.defaultCode || "";
        mount(LiveGamePlayer, root, { env, props });
    }
}

boot();
