# Design System Specification: The Celestial Veil

## 1. Overview & Creative North Star

### The Creative North Star: "Luminous Etherealism"
This design system is a departure from the cluttered, rigid "box-on-box" layouts typical of the streaming industry. Instead of mimicking a broadcast television interface, we are building a **Celestial Veil**—a sophisticated, multi-layered digital environment that feels as though it is floating in deep space. 

To achieve a "high-end editorial" feel, we reject the default grid. We embrace **intentional asymmetry**, where chat modules and alerts don't just sit next to the video feed—they graze it, overlap it, and interact with the negative space of the stream. This system uses breathing room (white space) not as a void, but as a luxury, allowing the vibrant pink and cyan accents to feel like precious light sources rather than UI noise.

---

## 2. Colors & Surface Philosophy

The palette is a high-contrast interplay between the void of space (`surface`: `#0d0d18`) and neon light.

### The "No-Line" Rule
**Explicit Instruction:** Do not use 1px solid borders to section off UI components. High-end design is felt, not outlined. Boundaries must be defined through:
*   **Background Shifts:** Placing a `surface-container-high` (`#1e1e2d`) card against a `surface` (`#0d0d18`) background.
*   **Tonal Transitions:** Using the subtle difference between `surface-container-low` and `surface-container-lowest`.

### Surface Hierarchy & Nesting
Treat the UI as a series of physical, stacked layers of frosted glass. 
1.  **Base Layer:** `surface-dim` (`#0d0d18`)
2.  **Sectional Layer:** `surface-container-low` (`#12121e`)
3.  **Interactive Layer (Cards/Chat):** `surface-container-high` (`#1e1e2d`)
4.  **Floating Elements (Pop-ups):** `surface-bright` (`#2b2a3c`)

### The "Glass & Gradient" Rule
For elements meant to feel premium (e.g., Sub Goals, Active Polling), use **Glassmorphism**. Apply a 20-40% opacity to your `surface-container` tokens and add a heavy `backdrop-blur` (16px+). 

To provide "soul," use subtle linear gradients for CTAs. A transition from `primary` (`#e08efe`) to `primary-container` (`#d180ef`) creates a soft, silk-like depth that flat hex codes cannot replicate.

---

## 3. Typography: Editorial Authority

We use a dual-font approach to balance professional legibility with the playful energy of the VTuber identity.

*   **Display & Headlines:** `plusJakartaSans`. This is our "Editorial" voice. Use `display-lg` (3.5rem) with tight letter-spacing for high-impact moments like "NEW FOLLOWER."
*   **Body & Labels:** `inter`. This is our "Functional" voice. It ensures chat messages and technical stats remain legible even at small scales.
*   **The Signature Style:** Typography hierarchy is driven by contrast. Pair a `headline-sm` in `primary` with a `label-sm` in `on-surface-variant` to create a clear, sophisticated information architecture.

---

## 4. Elevation & Depth

We convey hierarchy through **Tonal Layering** rather than structural lines.

*   **The Layering Principle:** Depth is achieved by "stacking." For instance, a chat message container should be `surface-container-highest` (`#242434`) sitting inside a chat rail of `surface-container-low` (`#12121e`).
*   **Ambient Shadows:** For floating alerts, use extra-diffused shadows. 
    *   *Shadow Color:* A 6% opacity version of `surface-tint` (`#e08efe`). 
    *   *Blur:* 30px to 50px. This mimics a soft purple glow from the "screen" rather than a dark grey drop shadow.
*   **The "Ghost Border" Fallback:** If accessibility requires a border, use the `outline-variant` (`#474754`) at **15% opacity**. It should be a whisper of a line, not a shout.
*   **Dynamic Rank Borders:** For VIPs or Moderators, use a 2px "Ghost Border" that utilizes `secondary` (`#fd6c9c`) for Mods and `tertiary` (`#81ecff`) for Subs, but apply a `soft glow` (5px blur) to the border itself to make it feel luminous.

---

## 5. Components

### Buttons & CTAs
*   **Primary:** A gradient of `primary` to `primary-container`. `xl` roundedness (1.5rem). No border.
*   **Secondary:** `surface-container-highest` with a `Ghost Border` of `primary`.
*   **Interaction:** On hover, apply a `pulsing glow` using the `primary_dim` color token.

### Chat & Message Cards
*   **Spacing:** Use vertical white space from the spacing scale instead of dividers.
*   **Styling:** Messages should have `md` rounded corners (0.75rem).
*   **User Ranks:** Usernames use `plusJakartaSans` (the accent font). Colors change based on rank (e.g., `tertiary` for Subs), but keep the message body `on-surface`.

### Input Fields (Chat Box)
*   **State:** Background should be `surface-container-lowest`. 
*   **Focus:** When active, the background shifts to `surface-container-high` with a subtle `tertiary` pulse.

### Progress Bars (Sub Goals)
*   **Track:** `surface-container-high`.
*   **Indicator:** A vibrant gradient of `secondary` to `secondary_dim`. Add a small "glow head" to the leading edge of the progress bar using a `secondary` drop shadow.

---

## 6. Do's and Don'ts

### Do
*   **Do** overlap UI elements (like a chat badge slightly breaking the container edge) to create a sense of depth.
*   **Do** use `full` roundedness (9999px) for status indicators and small chips.
*   **Do** favor `surface-variant` for non-essential text to maintain a hierarchy where the content is king.
*   **Do** use subtle floating animations (y-axis translation of 4-6px) for persistent UI elements like "Now Playing."

### Don't
*   **Don't** use 100% opaque, high-contrast borders. 
*   **Don't** use pure black (`#000000`) for anything other than the `surface-container-lowest` in extreme high-contrast needs.
*   **Don't** use hard-edged transitions. Every appearance should be a `fade-in` or a `soft-scale`.
*   **Don't** use "default" drop shadows. If it doesn't have a tint of purple or pink, it doesn't belong in this system.