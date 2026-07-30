import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { TextInput } from "@astryxdesign/core/TextInput";
import { FormEvent, useState } from "react";
import type { PaimAuthResponse } from "./auth";
import { getErrorMessage, fetchPaimPublicJson } from "./paimApi";
import { useI18n } from "./i18n";

type AuthMode = "login" | "signup";
type AuthField = "email" | "name" | "password";

type AuthScreenProps = {
  initialMessage?: string;
  onAuthenticated: (response: PaimAuthResponse) => void;
};

export function AuthScreen({ initialMessage = "", onAuthenticated }: AuthScreenProps) {
  const { language, t } = useI18n();
  const [mode, setMode] = useState<AuthMode>("login");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [errorMessage, setErrorMessage] = useState(initialMessage);
  const [fieldErrors, setFieldErrors] = useState<Partial<Record<AuthField, string>>>({});
  const [isSubmitting, setIsSubmitting] = useState(false);

  function switchMode(nextMode: AuthMode) {
    setMode(nextMode);
    setErrorMessage("");
    setFieldErrors({});
  }

  function updateField(field: AuthField, value: string) {
    if (field === "email") {
      setEmail(value);
    } else if (field === "name") {
      setName(value);
    } else {
      setPassword(value);
    }

    setFieldErrors((current) => {
      if (!current[field]) {
        return current;
      }

      const next = { ...current };
      delete next[field];
      return next;
    });
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    const normalizedEmail = email.trim().toLowerCase();
    const normalizedName = name.trim();

    if (!normalizedEmail.includes("@")) {
      setErrorMessage("");
      setFieldErrors({ email: t("유효한 이메일 주소를 입력해 주세요.") });
      return;
    }
    if (password.length < 8) {
      setErrorMessage("");
      setFieldErrors({ password: t("비밀번호는 8자 이상이어야 합니다.") });
      return;
    }
    if (mode === "signup" && !normalizedName) {
      setErrorMessage("");
      setFieldErrors({ name: t("이름을 입력해 주세요.") });
      return;
    }

    setIsSubmitting(true);
    setErrorMessage("");
    setFieldErrors({});

    try {
      const response = await fetchPaimPublicJson<PaimAuthResponse>(
        mode === "login" ? "/auth/login" : "/auth/signup",
        {
          method: "POST",
          body: JSON.stringify(
            mode === "login"
              ? { email: normalizedEmail, password }
              : { email: normalizedEmail, password, name: normalizedName },
          ),
        },
      );
      onAuthenticated(response);
    } catch (error) {
      setErrorMessage(getErrorMessage(error, t("로그인 요청을 완료할 수 없습니다.")));
    } finally {
      setIsSubmitting(false);
    }
  }

  return (
    <main className="auth-screen" aria-label={t(mode === "login" ? "로그인" : "회원가입")}>
      <div aria-hidden="true" className="native-titlebar-drag-region" data-tauri-drag-region />
      <section className="auth-card">
        <header className="auth-header">
          <h1
            aria-label={mode === "login" ? t("PaiM에 로그인") : undefined}
            className={mode === "login" ? "auth-login-title" : undefined}
          >
            {mode === "login" ? (
              <>
                {language === "en" ? <span aria-hidden="true">Sign in to</span> : null}
                <span aria-hidden="true" className="auth-brand-wordmark">
                  <span>P</span>
                  <span className="auth-brand-ai">ai</span>
                  <span>M</span>
                </span>
                {language === "ko" ? <span aria-hidden="true">에 로그인</span> : null}
              </>
            ) : (
              t("PaiM 계정 만들기")
            )}
          </h1>
          <p>
            {t(
              mode === "login"
                ? "프로젝트의 맥락과 팀 작업을 이어가세요."
                : "팀 프로젝트를 시작할 계정을 만듭니다.",
            )}
          </p>
        </header>

        {errorMessage ? (
          <Banner className="auth-error" container="card" status="error" title={t(errorMessage)} />
        ) : null}

        <form className="auth-form" onSubmit={handleSubmit}>
          {mode === "signup" ? (
            <TextInput
              hasAutoFocus
              htmlName="name"
              label={t("이름 (필수)")}
              onChange={(value) => updateField("name", value)}
              placeholder={t("팀에서 사용할 이름")}
              status={fieldErrors.name ? { message: fieldErrors.name, type: "error" } : undefined}
              value={name}
              width="100%"
            />
          ) : null}
          <TextInput
            hasAutoFocus={mode === "login"}
            htmlName="email"
            label={t("이메일 (필수)")}
            onChange={(value) => updateField("email", value)}
            placeholder="name@example.com"
            status={fieldErrors.email ? { message: fieldErrors.email, type: "error" } : undefined}
            type="email"
            value={email}
            width="100%"
          />
          <TextInput
            htmlName="password"
            label={t("비밀번호 (필수)")}
            onChange={(value) => updateField("password", value)}
            placeholder={t("8자 이상")}
            status={fieldErrors.password ? { message: fieldErrors.password, type: "error" } : undefined}
            type="password"
            value={password}
            width="100%"
          />
          <Button
            className="auth-submit"
            isLoading={isSubmitting}
            label={t(mode === "login" ? "로그인" : "계정 만들기")}
            type="submit"
            variant="primary"
          />
        </form>

        <div className="auth-switch">
          <span>{t(mode === "login" ? "계정이 없나요?" : "이미 계정이 있나요?")}</span>
          <Button
            label={t(mode === "login" ? "회원가입" : "로그인")}
            onClick={() => switchMode(mode === "login" ? "signup" : "login")}
            size="sm"
            variant="ghost"
          />
        </div>
      </section>
    </main>
  );
}
