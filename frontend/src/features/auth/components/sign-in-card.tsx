"use client";

import React, { useContext, useState } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import DottedSeparator from "@/components/ui/dotted-separator";
import { Button } from "@/components/ui/button";
import { GlobalContext } from "@/app/context/index";
import { loginFormControls } from "@/features/auth/constants";
import Input from "@/components/ui/input";
import CircleLoader from "@/components/ui/circleloader";
import { useFormik } from "formik";
import { signInSchema } from "../schema";
import { useAsyncLoader } from "@/hooks/use-async-loader";
import { apiFetch } from "@/lib/api";

const SignInCard = () => {
  const router = useRouter();
  const { pageLevelLoader, setCurrentUser } = useContext(GlobalContext)!;
  const run = useAsyncLoader();
  const [loginError, setLoginError] = useState<string | null>(null);

  const formik = useFormik({
    initialValues: {
      email: "",
      password: "",
    },
    validate: (values) => {
      const result = signInSchema.safeParse(values);
      if (!result.success) {
        return result.error.flatten().fieldErrors;
      }
      return {};
    },
    onSubmit: async (vals) => {
      setLoginError(null);
      await run(async () => {
        // Backend memverifikasi password & memasang cookie sesi httpOnly; proxy Next
        // (src/proxy.ts) lalu mengizinkan halaman & API.
        const r = await apiFetch("/api/v1/auth/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ email: vals.email, password: vals.password }),
        });
        if (!r.ok) {
          const d = await r.json().catch(() => ({}));
          setLoginError(typeof d.detail === "string" ? d.detail : `Login gagal (${r.status})`);
          return;
        }
        setCurrentUser(await r.json());
        // Hanya jalur internal yang boleh jadi tujuan (cegah open redirect).
        const next = new URLSearchParams(window.location.search).get("next");
        router.push(next && next.startsWith("/") && !next.startsWith("//") ? next : "/dashboards");
      });
    },
  });

  const { errors, touched, values, handleChange, handleSubmit } = formik;

  return (
    <Card className="w-full max-w-sm sm:max-w-md md:w-[487px] border border-gray-300 shadow-lg bg-white mx-auto">
      <CardHeader className="flex items-center justify-center text-center p-7">
        <CardTitle className="text-2xl">Welcome Back</CardTitle>
      </CardHeader>
      <div className="px-7 mb-4">
        <DottedSeparator />
      </div>
      <CardContent className="p-7">
        <form className="space-y-4" onSubmit={handleSubmit}>
          {loginFormControls.map((item, index) =>
            item.componentType === "input" ? (
              <Input
                key={index}
                id={item.id}
                label={item.label}
                type={item.type}
                value={values[item.id as keyof typeof values]}
                onChange={handleChange}
                errors={
                  touched[item.id as keyof typeof values]
                    ? errors[item.id as keyof typeof values]
                    : undefined
                }
                touched={touched[item.id as keyof typeof values]}
              />
            ) : null
          )}

          {loginError && (
            <p role="alert" className="text-sm text-red-600 bg-red-50 border border-red-200 rounded-lg px-3 py-2">{loginError}</p>
          )}

          <div className="flex flex-col mt-5">
            <Button size="lg" variant="primary" type="submit">
              {pageLevelLoader === true ? (
                <CircleLoader color={"#D3D3D3"} loading={pageLevelLoader} />
              ) : (
                "Login"
              )}
            </Button>
          </div>
        </form>
      </CardContent>

      <div className="px-7 mb-4">
        <DottedSeparator />
      </div>
    </Card>
  );
};

export default SignInCard;
