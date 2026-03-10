interface Option {
    id: string;
    label: string;
}


interface Props {
    id: string;
    type: string;
    placeholder: string;
    label: string;
    componentType: string; 
    options? : Option[];
}

export const loginFormControls: Props[] = [  
    {
        id: 'email',
        type: 'email',
        placeholder: 'Enter your email',
        label: 'Email',
        componentType: 'input',
    },
    {
        id: 'password',
        type: 'password',
        placeholder: 'Enter your password',
        label: 'Password',
        componentType: 'input',
    },
    // {
    //     id: 'personalgoal',
    //     type: '',
    //     placeholder: '',
    //     label: 'Personal Goal',
    //     componentType: 'select',
    //     options: [
    //         {
    //             id:'notfound',
    //             label: 'Pilih-Keahlian',
    //         },
    //         {
    //             id:'fs',
    //             label: 'Fullstack Developer',
    //         },
    //         {
    //             id:'be',
    //             label: 'Backend Developer',
    //         },
    //         {
    //             id:'fe',
    //             label: 'Frontend Developer',
    //         },
    //     ]
    // },
];
