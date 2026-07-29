import { useEffect, useState } from "react";

type ProfileAvatarProps = {
  ariaHidden?: boolean;
  ariaLabel?: string;
  className: string;
  fallback: string;
  imageUrl?: string | null;
  label?: string;
  size?: string;
};

export function ProfileAvatar({
  ariaHidden = false,
  ariaLabel,
  className,
  fallback,
  imageUrl,
  label,
  size,
}: ProfileAvatarProps) {
  const normalizedImageUrl = imageUrl?.trim() || "";
  const [failedImageUrl, setFailedImageUrl] = useState<string | null>(null);

  useEffect(() => {
    if (failedImageUrl && failedImageUrl !== normalizedImageUrl) {
      setFailedImageUrl(null);
    }
  }, [failedImageUrl, normalizedImageUrl]);

  const showImage = Boolean(normalizedImageUrl && failedImageUrl !== normalizedImageUrl);

  return (
    <span
      aria-hidden={ariaHidden || undefined}
      aria-label={ariaHidden ? undefined : ariaLabel}
      className={className}
      data-size={size}
      role={ariaHidden ? undefined : "img"}
      title={label}
    >
      {fallback}
      {showImage ? (
        <img
          alt=""
          onError={() => setFailedImageUrl(normalizedImageUrl)}
          referrerPolicy="no-referrer"
          src={normalizedImageUrl}
        />
      ) : null}
    </span>
  );
}
