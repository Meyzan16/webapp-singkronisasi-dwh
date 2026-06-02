interface FormControl {
  id: string;
  type: string;
  placeholder: string;
  label: string;
  componentType: string;
}

export const loginFormControls: FormControl[] = [
  {
    id: "email",
    type: "email",
    placeholder: "Enter your email",
    label: "Email",
    componentType: "input",
  },
  {
    id: "password",
    type: "password",
    placeholder: "Enter your password",
    label: "Password",
    componentType: "input",
  },
];
