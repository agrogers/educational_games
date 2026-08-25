/**
 * Live realtime games — perimeter track renderer.
 *
 * The race track runs along the outside edge of the screen: it starts at
 * the top-left corner, runs clockwise (top edge → right edge → bottom
 * edge) and finishes at the bottom-right corner.  Avatars are absolutely
 * positioned DOM nodes moved by progress fraction (0..1).
 *
 * Used identically by the host console and the student player so every
 * screen shows avatars at the same spot.
 */

const MARGIN = 28; // px kept from the viewport edges

/**
 * Compute the {x, y} pixel position for a progress fraction.
 *
 * @param {number} fraction 0..1 around the track
 * @param {number} [width]  container width  (defaults to window.innerWidth)
 * @param {number} [height] container height (defaults to window.innerHeight)
 * @returns {{x: number, y: number}}
 */
export function trackPosition(fraction, width = window.innerWidth, height = window.innerHeight) {
    const f = Math.max(0, Math.min(1, Number(fraction) || 0));
    const left = MARGIN;
    const right = width - MARGIN;
    const top = MARGIN;
    const bottom = height - MARGIN;
    const spanX = right - left;
    const spanY = bottom - top;

    // Segment lengths: top edge, right edge, bottom edge (finish at
    // bottom-right).  Left edge is unused — the track is a "U" shape.
    const perimTop = spanX;
    const perimRight = spanY;
    const total = perimTop + perimRight + spanX;

    let distance = f * total;
    if (distance <= perimTop) {
        return { x: left + distance, y: top };
    }
    distance -= perimTop;
    if (distance <= perimRight) {
        return { x: right, y: top + distance };
    }
    distance -= perimRight;
    return { x: right - distance, y: bottom };
}

/**
 * Create a track manager bound to a container element.  Avatars are
 * created/updated from participant data; call `layout()` on resize.
 */
export function createTrack(container) {
    const avatarEls = new Map(); // participant id -> element

    function ensureAvatar(participant) {
        let el = avatarEls.get(participant.id);
        if (!el) {
            el = document.createElement("div");
            el.className = "lg-avatar";
            el.dataset.avatarId = participant.id;
            const dot = document.createElement("div");
            dot.className = `lg-avatar-dot lg-avatar-${participant.avatar || "red"}`;
            const label = document.createElement("div");
            label.className = "lg-avatar-label";
            el.appendChild(dot);
            el.appendChild(label);
            container.appendChild(el);
            avatarEls.set(participant.id, el);
        }
        const labelEl = el.querySelector(".lg-avatar-label");
        if (labelEl.textContent !== participant.nickname) {
            labelEl.textContent = participant.nickname;
        }
        return el;
    }

    /**
     * Sync the rendered avatars with the given participants and move them
     * to their positions.
     *
     * @param {Array<{id: number, nickname: string, avatar: string,
     *                position: number}>} participants
     */
    function render(participants) {
        const seen = new Set();
        for (const participant of participants) {
            seen.add(participant.id);
            const el = ensureAvatar(participant);
            const { x, y } = trackPosition((participant.position || 0) / 100);
            el.style.transform = `translate(${x}px, ${y}px)`;
            el.classList.toggle("lg-avatar-finished", participant.state === "finished");
        }
        // Remove avatars of participants that left.
        for (const [id, el] of avatarEls) {
            if (!seen.has(id)) {
                el.remove();
                avatarEls.delete(id);
            }
        }
    }

    /** Re-place all avatars (viewport resize / orientation change). */
    function layout() {
        for (const [, el] of avatarEls) {
            const id = Number(el.dataset.avatarId);
            const participant = avatarParticipants.get(id);
            if (participant) {
                const { x, y } = trackPosition((participant.position || 0) / 100);
                el.style.transform = `translate(${x}px, ${y}px)`;
            }
        }
    }

    const avatarParticipants = new Map();

    return {
        render(participants) {
            for (const p of participants) {
                avatarParticipants.set(p.id, p);
            }
            render(participants);
        },
        layout,
        clear() {
            for (const [, el] of avatarEls) {
                el.remove();
            }
            avatarEls.clear();
            avatarParticipants.clear();
        },
    };
}
