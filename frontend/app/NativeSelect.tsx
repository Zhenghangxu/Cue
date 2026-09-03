import type { ComponentProps } from "react";
import { ChevronDown } from "lucide-react";

export function NativeSelect(props: ComponentProps<"select">) {
  return (
    <span className="nativeSelect" data-slot="native-select-wrapper">
      <select data-slot="native-select" {...props} />
      <ChevronDown
        size={16}
        strokeWidth={1.75}
        aria-hidden="true"
        data-slot="native-select-icon"
      />
    </span>
  );
}
