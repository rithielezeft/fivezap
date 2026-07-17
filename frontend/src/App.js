import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import "@/App.css";

import Dashboard from "@/pages/Dashboard";
import Customers from "@/pages/Customers";
import Trials from "@/pages/Trials";
import Templates from "@/pages/Templates";
import WhatsAppPage from "@/pages/WhatsAppPage";
import Messages from "@/pages/Messages";
import Payments from "@/pages/Payments";
import Settings from "@/pages/Settings";
import Notifications from "@/pages/Notifications";
import PublicTest from "@/pages/PublicTest";
import PublicPay from "@/pages/PublicPay";

export default function App() {
  return (
    <>
      <BrowserRouter>
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/customers" element={<Customers />} />
          <Route path="/trials" element={<Trials />} />
          <Route path="/templates" element={<Templates />} />
          <Route path="/whatsapp" element={<WhatsAppPage />} />
          <Route path="/messages" element={<Messages />} />
          <Route path="/payments" element={<Payments />} />
          <Route path="/notifications" element={<Notifications />} />
          <Route path="/settings" element={<Settings />} />
          <Route path="/teste" element={<PublicTest />} />
          <Route path="/pay/:customerId" element={<PublicPay />} />
        </Routes>
      </BrowserRouter>
      <Toaster theme="dark" position="top-right" richColors closeButton />
    </>
  );
}
