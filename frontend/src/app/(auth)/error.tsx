"use client"

import { Button } from '@/components/ui/button'
import { AlertTriangle } from 'lucide-react'
import Link from 'next/link'
import React from 'react'

const ErrorPage = () => {
  return (
    <div className='h-screen flex items-center justify-center flex-col gap-y-4'>
        <AlertTriangle />
        <p className='text-sm text-muted-foreground'>
            Something went wrong. Please try again later.
        </p>
        <Button variant='secondary' size='md' className='text-sm'>
            <Link href={`/`}>
                Back to Home
            </Link>
        </Button>
    </div>
  )
}

export default ErrorPage