"use client"

import CircleLoader from '@/components/ui/circleloader'
import React from 'react'

const LoadingPage = () => {
  return (
    <div className="h-full min-h-screen flex items-center justify-center">
            <CircleLoader color={"#D3D3D3"} loading={true} />
        </div>
  )
}

export default LoadingPage