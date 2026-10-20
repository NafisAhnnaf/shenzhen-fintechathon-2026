import { type HTMLAttributes, forwardRef } from "react";

export type AlertVariant = "default" | "destructive" | "warning" | "success";

export interface AlertProps extends HTMLAttributes<HTMLDivElement> {
  variant?: AlertVariant;
  onClose?: () => void;
}

export const Alert = forwardRef<HTMLDivElement, AlertProps>(
  ({ className = "", variant = "default", onClose, children, ...props }, ref) => {
    return (
      <div
        ref={ref}
        role="alert"
        className={`shadcn-alert shadcn-alert-${variant} ${className}`}
        {...props}
      >
        <div className="shadcn-alert-body">
          {children}
        </div>
        {onClose && (
          <button
            type="button"
            className="shadcn-alert-close"
            onClick={onClose}
            aria-label="Dismiss alert"
          >
            <svg
              viewBox="0 0 24 24"
              width="16"
              height="16"
              fill="none"
              stroke="currentColor"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            >
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        )}
      </div>
    );
  }
);
Alert.displayName = "Alert";

export const AlertTitle = forwardRef<HTMLHeadingElement, HTMLAttributes<HTMLHeadingElement>>(
  ({ className = "", children, ...props }, ref) => (
    <h5
      ref={ref}
      className={`shadcn-alert-title ${className}`}
      {...props}
    >
      {children}
    </h5>
  )
);
AlertTitle.displayName = "AlertTitle";

export const AlertDescription = forwardRef<HTMLParagraphElement, HTMLAttributes<HTMLParagraphElement>>(
  ({ className = "", children, ...props }, ref) => (
    <div
      ref={ref}
      className={`shadcn-alert-description ${className}`}
      {...props}
    >
      {children}
    </div>
  )
);
AlertDescription.displayName = "AlertDescription";

export function AlertCircleIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`shadcn-alert-icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <circle cx="12" cy="12" r="10" />
      <line x1="12" y1="8" x2="12" y2="12" />
      <line x1="12" y1="16" x2="12.01" y2="16" />
    </svg>
  );
}

export function AlertTriangleIcon({ className = "" }: { className?: string }) {
  return (
    <svg
      className={`shadcn-alert-icon ${className}`}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" />
      <line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}
