"use client";

import { FC, useState } from "react";
import { Eye, EyeOff } from "lucide-react";

interface InputProps {
  label?: string;
  type: string;
  value: string | undefined;
  onChange: React.ChangeEventHandler<HTMLInputElement>;
  id: string;
  placeholder?: string;
  errors?: string;
  touched?: boolean;
}

const Input: FC<InputProps> = ({
  id,
  label,
  type,
  value,
  onChange,
  errors,
  touched,
  placeholder
}) => {
  const [isFilledOrFocused, setIsFilledOrFocused] = useState(
    () => !!value && value.toString().length > 0,
  );
  const [showPassword, setShowPassword] = useState(false);

  const isPasswordInput = type === "password";

  return (
    <div className={`relative w-full ${errors && touched ? "mb-4" : "mb-4"}`}>
      <label
        className={`absolute left-4 transition-all duration-300 bg-white px-2
          ${
            isFilledOrFocused
              ? "-top-2 text-xs text-gray-600"
              : "top-4 text-base text-gray-400"
          }`}
        htmlFor={id}
      >
        {label}
      </label>

      <input
        id={id}
        type={isPasswordInput ? (showPassword ? "text" : "password") : type}
        value={value}
        onChange={(e) => {
          onChange(e);
          setIsFilledOrFocused(e.target.value.length > 0);
        }}
        placeholder={placeholder}
        onFocus={() => setIsFilledOrFocused(true)}
        aria-label={label}
        className={`w-full px-4 pt-5 pb-2 border rounded-full  
                    font-poppins 
                    text-base shadow-sm transition-colors 
                    placeholder:text-muted-foreground 
                    focus-visible:outline-none 
                    focus-visible:ring-1 
                    focus-visible:ring-ring
                    disabled:cursor-not-allowed 
                    disabled:opacity-50 md:text-sm
                    ${
                      errors && touched ? "border-red-500" : "border-gray-300"
                    }`}
      />

      {isPasswordInput && (
        <span
          className="absolute top-4 right-3 cursor-pointer text-black z-10"
          onClick={() => setShowPassword((prev) => !prev)}
        >
          {showPassword ? (
            <Eye size={20} />
          ) : (
            <EyeOff size={20} />
          )}
        </span>
      )}

      {errors && touched && (
        <span className="text-red-500 block font-poppins text-base mt-2">
          {errors}
        </span>
      )}
    </div>
  );
};

export default Input;
