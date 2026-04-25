"use client";

import React, { useContext } from "react";
import { useRouter } from "next/navigation";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import DottedSeparator from "@/components/ui/dotted-separator";
import { Button } from "@/components/ui/button";
import { GlobalContext } from "@/app/context/index";
import { loginFormControls } from "@/constants/auth-controls";
import Input from "@/components/ui/input";
import CircleLoader from "@/components/ui/circleloader";
import { useFormik } from "formik";
import { signInSchema } from "../schema";
import { useAsyncLoader } from "@/hooks/use-async-loader";

const SignInCard = () => {
  const router = useRouter();
  const { pageLevelLoader } = useContext(GlobalContext)!;
  const run = useAsyncLoader();

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
    onSubmit: async () => {
      await run(async () => {
        // TODO: ganti dengan pemanggilan API login nyata
        await new Promise((resolve) => setTimeout(resolve, 800));
        router.push("/dashboards");
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
