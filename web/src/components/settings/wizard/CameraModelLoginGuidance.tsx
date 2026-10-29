// SPDX-License-Identifier: LicenseRef-GNCL-1.0

import { useTranslation } from "react-i18next";
import type { CameraModel, CameraModelNote } from "@/types/cameraModels";

/** Public initial login information only. Never reads or changes the form. */
export default function CameraModelLoginGuidance({
  model,
}: {
  model: CameraModel;
}) {
  const { t } = useTranslation(["views/settings"]);
  const login = model.login;
  const notes: Record<CameraModelNote, string> = {
    firstChange: t("cameraWizard.step1.modelLogin.firstChange"),
    reolink: t("cameraWizard.step1.modelLogin.reolink"),
    hikvision: t("cameraWizard.step1.modelLogin.hikvision"),
    tapoDualLens: t("cameraWizard.step1.modelLogin.tapoDualLens"),
    avigilon2020: t("cameraWizard.step1.modelLogin.avigilon2020"),
    aiphone: t("cameraWizard.step1.modelLogin.aiphone"),
    wyze: t("cameraWizard.step1.modelLogin.wyzeFirmware"),
    unverifiedStream: t("cameraWizard.step1.modelLogin.unverifiedStream"),
  };
  const providerText = {
    protect: t("cameraWizard.step1.modelLogin.protect"),
    eufy: t("cameraWizard.step1.modelLogin.eufy"),
    wyze: t("cameraWizard.step1.modelLogin.wyze"),
  };

  return (
    <section
      aria-label={t("cameraWizard.step1.modelLogin.heading")}
      aria-live="polite"
      className="space-y-1.5 rounded-md border bg-muted/40 p-3 text-xs"
    >
      <p className="font-semibold">
        {t("cameraWizard.step1.modelLogin.heading")}: {model.manufacturer}{" "}
        {model.name}
      </p>
      {(login.kind === "factory" || login.kind === "blank") && (
        <>
          <p className="font-medium">
            {t("cameraWizard.step1.modelLogin.initialLogin")}
          </p>
          <dl className="grid grid-cols-[auto_1fr] gap-x-2 gap-y-0.5">
            <dt>{t("cameraWizard.step1.modelLogin.username")}</dt>
            <dd>
              <code>{login.username}</code>
            </dd>
            <dt>{t("cameraWizard.step1.modelLogin.password")}</dt>
            <dd>
              {login.kind === "blank" ? (
                t("cameraWizard.step1.modelLogin.blank")
              ) : (
                <code>{login.password}</code>
              )}
            </dd>
          </dl>
        </>
      )}
      {login.kind === "activation" && (
        <>
          <p>{t("cameraWizard.step1.modelLogin.activation")}</p>
          {login.username && (
            <p>
              {t("cameraWizard.step1.modelLogin.username")}{" "}
              <code>{login.username}</code>
            </p>
          )}
        </>
      )}
      {login.kind === "cameraAccount" && (
        <p>{t("cameraWizard.step1.modelLogin.cameraAccount")}</p>
      )}
      {login.kind === "deviceLabel" && (
        <>
          <p>
            {t("cameraWizard.step1.modelLogin.username")}{" "}
            <code>{login.username}</code>
          </p>
          <p>
            {login.label === "verificationCode"
              ? t("cameraWizard.step1.modelLogin.verificationCode")
              : t("cameraWizard.step1.modelLogin.devicePassword")}
          </p>
        </>
      )}
      {login.kind === "providerUrl" && <p>{providerText[login.provider]}</p>}
      {model.note && <p>{notes[model.note]}</p>}
      <p className="text-muted-foreground">
        {t("cameraWizard.step1.modelLogin.caution")}
      </p>
      <div className="flex flex-wrap gap-x-3 gap-y-1">
        <a
          className="underline underline-offset-2"
          href={model.sourceUrl}
          target="_blank"
          rel="noopener noreferrer"
        >
          {t("cameraWizard.step1.modelLogin.source")}
        </a>
        {model.streamSourceUrl && (
          <a
            className="underline underline-offset-2"
            href={model.streamSourceUrl}
            target="_blank"
            rel="noopener noreferrer"
          >
            {t("cameraWizard.step1.modelLogin.streamSource")}
          </a>
        )}
      </div>
    </section>
  );
}
