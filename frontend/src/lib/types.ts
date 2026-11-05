export type Money = {
  minor: number;
  currency: string;
  formatted: string;
};

export type Health = {
  status: string;
  today: string;
  demo_today: string | null;
};

export type Organization = {
  name: string;
  address: string;
  accounts_contact_name: string;
  accounts_email: string;
  phone: string;
  default_currency: string;
  accepted_currencies: string[];
  payment_terms: string;
  payment_methods: string[];
  bank_details: {
    account_name: string;
    account_number: string;
    bank: string;
    ifsc: string;
    swift_code: string;
  };
  policies: {
    tds: string;
    bank_charges: string;
    extensions: string;
    disputes: string;
    working_hours: string;
  };
};

export type Customer = {
  customer_id: string;
  name: string;
  contact_name: string;
  contact_email: string;
  phone: string;
  city: string;
  country: string;
  currency: string;
};

export type LineItem = {
  description: string;
  quantity: number;
  unit_price: Money;
  amount: Money;
};

export type InvoiceStatus = "draft" | "sent" | "paid";

export type Invoice = {
  invoice_number: string;
  customer_id: string;
  customer_name: string;
  po_number: string | null;
  invoice_date: string;
  due_date: string;
  payment_terms: string;
  currency: string;
  line_items: LineItem[];
  subtotal: Money;
  discount: Money;
  tax_name: string;
  tax: Money;
  total: Money;
  amount_paid: Money;
  balance_due: Money;
  tds_written_off: Money;
  status: InvoiceStatus;
  is_overdue: boolean;
  unpaid_balance: Money;
};

export type ResetResponse = {
  ok: boolean;
  message: string;
  counts: Record<string, number>;
};
