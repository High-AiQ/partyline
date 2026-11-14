import { mount } from "svelte";
import A11yLab from "./A11yLab.svelte";
import "./a11y-lab.css";

const root = document.getElementById("root");
if (!root) throw new Error("accessibility lab requires a #root mount element");

export default mount(A11yLab, { target: root });
