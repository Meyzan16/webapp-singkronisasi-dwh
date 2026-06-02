"use client";

import React, { useState } from "react";
import DatePicker from "react-datepicker";
import "react-datepicker/dist/react-datepicker.css"; // For styling
import { Button } from "@/components/ui/button";
import { CalendarIcon } from "lucide-react";

interface DatePickerProps {
  value: [Date | null, Date | null];
  onChange: (value: [Date | null, Date | null]) => void;
}

export default function CustomDatePicker({ value, onChange }: DatePickerProps) {
  const [isOpen, setIsOpen] = useState(false);

  const handlePresetChange = (preset: string) => {
    const today = new Date();
    let startDate: Date | null = null;
    let endDate: Date | null = null;

    if (preset === "Last 7 Days") {
      startDate = new Date(today);
      startDate.setDate(today.getDate() - 7);
      endDate = today;
    } else if (preset === "Last 30 Days") {
      startDate = new Date(today);
      startDate.setDate(today.getDate() - 30);
      endDate = today;
    } else if (preset === "This Month") {
      startDate = new Date(today.getFullYear(), today.getMonth(), 1);
      endDate = today;
    }

    onChange([startDate, endDate]);
  };

  return (
    <div className="relative">
      <Button
        size="sm"
        variant="outline"
        className="flex items-center gap-2 border-gray-200"
        onClick={() => setIsOpen(!isOpen)}
      >
        <CalendarIcon size={16} />
        {value[0] && value[1]
          ? `${value[0]?.toLocaleDateString()} - ${value[1]?.toLocaleDateString()}`
          : "Select Date Range"}
      </Button>

      {isOpen && (
        <div className="absolute right-0 z-10 mt-2 w-96 rounded-lg border bg-white shadow-lg p-4">
          {/* Predefined Date Ranges */}
          <div className="flex space-x-2 mb-3">
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => handlePresetChange("Last 7 Days")}
            >
              Last 7 Days
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => handlePresetChange("Last 30 Days")}
            >
              Last 30 Days
            </Button>
            <Button
              variant="outline"
              size="sm"
              className="w-full"
              onClick={() => handlePresetChange("This Month")}
            >
              This Month
            </Button>
          </div>

          {/* Calendar with selected date range */}
          <div className="mt-4 w-full">
            <DatePicker
              selected={value[0]}
              onChange={(dates) => {
                if (Array.isArray(dates)) {
                  onChange([dates[0], dates[1]]);
                } else {
                  onChange([null, null]);
                }
              }}
              startDate={value[0]}
              endDate={value[1]}
              selectsRange
              inline
            />
          </div>

          {/* Buttons for Apply / Cancel */}
          <div className="mt-4 flex justify-between">
            <Button variant="outline" size="sm" onClick={() => setIsOpen(false)}>
              Cancel
            </Button>
            <Button size="sm" onClick={() => setIsOpen(false)}>
              Apply
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}