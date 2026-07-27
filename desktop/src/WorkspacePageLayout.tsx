import type { ComponentPropsWithoutRef, ReactNode } from "react";

type WorkspacePageLayoutProps = {
  ariaLabel: string;
  aside?: ReactNode;
  asideAriaLabel?: string;
  asideClassName?: string;
  children: ReactNode;
  className?: string;
  contentClassName?: string;
  layoutClassName?: string;
  mainClassName?: string;
  sectionProps?: WorkspaceSectionProps;
};

type WorkspaceSectionProps = Omit<
  ComponentPropsWithoutRef<"section">,
  "aria-label" | "children" | "className"
> & {
  [key: `data-${string}`]: number | string | undefined;
};

function classNames(...values: Array<string | undefined>) {
  return values.filter(Boolean).join(" ");
}

/**
 * Shared application-page frame.
 *
 * Project setup, Settings, Profile, and Members all use this structure so
 * their outer width, surface, spacing, and optional context rail stay aligned.
 */
export function WorkspacePageLayout({
  ariaLabel,
  aside,
  asideAriaLabel,
  asideClassName,
  children,
  className,
  contentClassName,
  layoutClassName,
  mainClassName,
  sectionProps,
}: WorkspacePageLayoutProps) {
  const hasAside = aside !== undefined && aside !== null;

  return (
    <section
      {...sectionProps}
      aria-label={ariaLabel}
      className={classNames("workspace-page", className)}
    >
      <div
        className={classNames("workspace-page-layout", layoutClassName)}
        data-has-aside={hasAside ? "true" : "false"}
      >
        <div className={classNames("workspace-page-main", mainClassName)}>
          <div className={classNames("workspace-page-body", contentClassName)}>
            {children}
          </div>
        </div>
        {hasAside ? (
          <aside
            aria-label={asideAriaLabel}
            className={classNames("workspace-page-aside", asideClassName)}
          >
            {aside}
          </aside>
        ) : null}
      </div>
    </section>
  );
}
