# Design QA — shared workspace layout / project setup

## Target and implementation

- Visual target: selected project-home proposal 1
- Target bitmap: `1672 × 941`, normalized to `1280 × 720` for comparison
- Viewport / CSS size: `1280 × 720`
- Implementation bitmap: `1280 × 720`
- Density normalization: `1 CSS px = 1 bitmap px`; target was resized to the same viewport for comparison.
- State: dark theme, offline saved-project mode, newly created project, no description or source, GitHub unlinked.

## Shared-layout evidence

- `desktop/src/WorkspacePageLayout.tsx` owns the common page surface, body, and optional context rail.
- Project setup, Settings, Profile, and Members all render through the same component.
- `desktop/src/styles.css` owns shared width, gap, surface, radius, status placement, responsive stacking, and high-zoom rules through `.workspace-page*` tokens.

## Visual comparison

- Full-view evidence is sufficient because the full 1280 × 720 project setup flow, status row, sidebar, main work surface, context rail, and bottom actions are simultaneously visible.
- The implementation matches the target hierarchy: quiet connection status, one setup surface, three-step progress, labeled description, restrained dashed upload zone, one primary action, and a top-aligned project-context rail.
- Minor expected state differences:
  - The reference uses an active primary CTA despite empty context; the implementation preserves the real disabled contract and uses a subdued accent treatment until context is added.
  - The reference shows an active `New Chat`; the implementation correctly shows a project with no auto-created chat.
  - The browser preview retains the user's previously resized sidebar. New installs use the shared `264px` default while retaining user resize persistence.

## Comparison history

1. Pass 1 exposed a taller-than-target work surface, a visually neutral disabled CTA, and strong programmatic heading focus.
2. The shared page bottom inset was tightened, the disabled primary action kept its semantic state while receiving restrained accent hierarchy, and non-interactive heading focus decoration was removed.
3. Final comparison found no P0, P1, or P2 visual defects. Layout and offline bundle regression suites passed, including 200% project-home stacking without horizontal overflow.

final result: passed
