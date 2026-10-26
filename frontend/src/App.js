import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "sonner";
import { useEffect } from "react";
import "@/App.css";
import { settingsApi, setDisplayTimezone } from "@/lib/api";

import Dashboard from "@/pages/Dashboard";
import Customers from "@/pages/Customers";
import Trials from "@/pages/Trials";
import Templates from "@/pages/Templates";
import WhatsAppPage from "@/pages/WhatsAppPage";
import Messages from "@/pages/Messages";
import Payments from "@/pages/Payments";
import Settings from "@/pages/Settings";
import Notifications from "@/pages/Notifications";
import Coupons from "@/pages/Coupons";
import Geography from "@/pages/Geography";
import ApiDocs from "@/pages/ApiDocs";
import Login from "@/pages/Login";
import PublicTest from "@/pages/PublicTest";
import PublicPay from "@/pages/PublicPay";
import ProtectedRoute from "@/components/ProtectedRoute";

const P = ({ children }) => <ProtectedRoute>{children}</ProtectedRoute>;

export default function App() {
  // Load the admin's timezone preference once at startup so ALL formatted
  // dates on the app reflect it (formatDateBR reads this value).
  useEffect(() => {
    settingsApi
      .get()
      .then((s) => setDisplayTimezone(s?.display_timezone || "America/Sao_Paulo"))
      .catch(() => {});
  }, []);

  return (
    <>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={<Login />} />
          <Route path="/teste" element={<PublicTest />} />
          <Route path="/pay/:customerId" element={<PublicPay />} />

          <Route path="/" element={<P><Dashboard /></P>} />
          <Route path="/customers" element={<P><Customers /></P>} />
          <Route path="/trials" element={<P><Trials /></P>} />
          <Route path="/templates" element={<P><Templates /></P>} />
          <Route path="/whatsapp" element={<P><WhatsAppPage /></P>} />
          <Route path="/messages" element={<P><Messages /></P>} />
          <Route path="/payments" element={<P><Payments /></P>} />
          <Route path="/notifications" element={<P><Notifications /></P>} />
          <Route path="/coupons" element={<P><Coupons /></P>} />
          <Route path="/geografia" element={<P><Geography /></P>} />
          <Route path="/documentacao" element={<P><ApiDocs /></P>} />
          <Route path="/settings" element={<P><Settings /></P>} />
        </Routes>
      </BrowserRouter>
      <Toaster theme="dark" position="top-right" richColors closeButton />
    </>
  );
}
