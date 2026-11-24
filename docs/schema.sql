\restrict NL23Ssp0JibzdfPeHgfQFzNy7CpS2UE6AW8Fl5xey1DhAefnMykzuMRrtpgA1i9
CREATE TABLE public.audit_events (
    id integer NOT NULL,
    document_id character varying(36) NOT NULL,
    event_type character varying(40) NOT NULL,
    field character varying(100),
    old_value jsonb,
    new_value jsonb,
    actor character varying(100) NOT NULL,
    details jsonb,
    created_at timestamp with time zone NOT NULL
);
ALTER TABLE public.audit_events OWNER TO idp;
CREATE SEQUENCE public.audit_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.audit_events_id_seq OWNER TO idp;
ALTER SEQUENCE public.audit_events_id_seq OWNED BY public.audit_events.id;
CREATE TABLE public.documents (
    id character varying(36) NOT NULL,
    filename character varying(255) NOT NULL,
    content_type character varying(50) NOT NULL,
    size_bytes integer NOT NULL,
    sha256 character varying(64) NOT NULL,
    storage_path character varying(512) NOT NULL,
    status character varying(20) NOT NULL,
    doc_type character varying(20),
    classification_confidence double precision,
    error_message text,
    retry_count integer NOT NULL,
    ocr_text text,
    ocr_method character varying(20),
    ocr_mean_confidence double precision,
    extractor character varying(20),
    extracted jsonb,
    data jsonb,
    confidence jsonb,
    created_at timestamp with time zone NOT NULL,
    updated_at timestamp with time zone NOT NULL,
    queued_at timestamp with time zone,
    processing_started_at timestamp with time zone,
    processed_at timestamp with time zone,
    approved_at timestamp with time zone,
    approved_by character varying(100)
);
ALTER TABLE public.documents OWNER TO idp;
CREATE TABLE public.validation_issues (
    id integer NOT NULL,
    document_id character varying(36) NOT NULL,
    code character varying(40) NOT NULL,
    severity character varying(10) NOT NULL,
    field character varying(100),
    message text NOT NULL,
    acknowledged boolean NOT NULL,
    acknowledged_by character varying(100),
    acknowledged_note text,
    created_at timestamp with time zone NOT NULL
);
ALTER TABLE public.validation_issues OWNER TO idp;
CREATE SEQUENCE public.validation_issues_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;
ALTER SEQUENCE public.validation_issues_id_seq OWNER TO idp;
ALTER SEQUENCE public.validation_issues_id_seq OWNED BY public.validation_issues.id;
ALTER TABLE ONLY public.audit_events ALTER COLUMN id SET DEFAULT nextval('public.audit_events_id_seq'::regclass);
ALTER TABLE ONLY public.validation_issues ALTER COLUMN id SET DEFAULT nextval('public.validation_issues_id_seq'::regclass);
ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.documents
    ADD CONSTRAINT documents_pkey PRIMARY KEY (id);
ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT validation_issues_pkey PRIMARY KEY (id);
CREATE INDEX ix_audit_events_created_at ON public.audit_events USING btree (created_at);
CREATE INDEX ix_audit_events_document_id ON public.audit_events USING btree (document_id);
CREATE INDEX ix_audit_events_event_type ON public.audit_events USING btree (event_type);
CREATE INDEX ix_documents_doc_type ON public.documents USING btree (doc_type);
CREATE UNIQUE INDEX ix_documents_sha256 ON public.documents USING btree (sha256);
CREATE INDEX ix_documents_status ON public.documents USING btree (status);
CREATE INDEX ix_validation_issues_code ON public.validation_issues USING btree (code);
CREATE INDEX ix_validation_issues_document_id ON public.validation_issues USING btree (document_id);
ALTER TABLE ONLY public.audit_events
    ADD CONSTRAINT audit_events_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;
ALTER TABLE ONLY public.validation_issues
    ADD CONSTRAINT validation_issues_document_id_fkey FOREIGN KEY (document_id) REFERENCES public.documents(id) ON DELETE CASCADE;
\unrestrict NL23Ssp0JibzdfPeHgfQFzNy7CpS2UE6AW8Fl5xey1DhAefnMykzuMRrtpgA1i9
