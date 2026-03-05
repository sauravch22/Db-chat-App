--
-- Pagila Database – Table Import Script
-- Stripped of functions, views, triggers, rules, and ownership statements.
-- PostgreSQL 17+
--

SET statement_timeout = 0;
SET lock_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET client_min_messages = warning;
SET row_security = off;

-- ══════════════════════════════════════════════════════
--  CUSTOM TYPES & DOMAINS
-- ══════════════════════════════════════════════════════

CREATE TYPE public.mpaa_rating AS ENUM (
    'G', 'PG', 'PG-13', 'R', 'NC-17'
);

CREATE DOMAIN public.year AS integer
    CONSTRAINT year_check CHECK (((VALUE >= 1901) AND (VALUE <= 2155)));

-- ══════════════════════════════════════════════════════
--  SEQUENCES
-- ══════════════════════════════════════════════════════

CREATE SEQUENCE public.actor_actor_id_seq       START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.address_address_id_seq   START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.category_category_id_seq START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.city_city_id_seq         START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.country_country_id_seq   START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.customer_customer_id_seq START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.film_film_id_seq         START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.inventory_inventory_id_seq START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.language_language_id_seq START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.payment_payment_id_seq   START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.rental_rental_id_seq     START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.staff_staff_id_seq       START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;
CREATE SEQUENCE public.store_store_id_seq       START WITH 1 INCREMENT BY 1 NO MINVALUE NO MAXVALUE CACHE 1;

-- ══════════════════════════════════════════════════════
--  TABLES
-- ══════════════════════════════════════════════════════

-- 1. country
CREATE TABLE public.country (
    country_id   integer DEFAULT nextval('public.country_country_id_seq'::regclass) NOT NULL,
    country      character varying(50) NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 2. city
CREATE TABLE public.city (
    city_id      integer DEFAULT nextval('public.city_city_id_seq'::regclass) NOT NULL,
    city         character varying(50) NOT NULL,
    country_id   smallint NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 3. address
CREATE TABLE public.address (
    address_id   integer DEFAULT nextval('public.address_address_id_seq'::regclass) NOT NULL,
    address      character varying(50) NOT NULL,
    address2     character varying(50),
    district     character varying(20) NOT NULL,
    city_id      smallint NOT NULL,
    postal_code  character varying(10),
    phone        character varying(20) NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 4. store
CREATE TABLE public.store (
    store_id          integer DEFAULT nextval('public.store_store_id_seq'::regclass) NOT NULL,
    manager_staff_id  smallint NOT NULL,
    address_id        smallint NOT NULL,
    last_update       timestamp without time zone DEFAULT now() NOT NULL
);

-- 5. staff
CREATE TABLE public.staff (
    staff_id     integer DEFAULT nextval('public.staff_staff_id_seq'::regclass) NOT NULL,
    first_name   character varying(45) NOT NULL,
    last_name    character varying(45) NOT NULL,
    address_id   smallint NOT NULL,
    email        character varying(50),
    store_id     smallint NOT NULL,
    active       boolean DEFAULT true NOT NULL,
    username     character varying(16) NOT NULL,
    password     character varying(40),
    last_update  timestamp without time zone DEFAULT now() NOT NULL,
    picture      bytea
);

-- 6. customer
CREATE TABLE public.customer (
    customer_id  integer DEFAULT nextval('public.customer_customer_id_seq'::regclass) NOT NULL,
    store_id     smallint NOT NULL,
    first_name   character varying(45) NOT NULL,
    last_name    character varying(45) NOT NULL,
    email        character varying(50),
    address_id   smallint NOT NULL,
    activebool   boolean DEFAULT true NOT NULL,
    create_date  date DEFAULT CURRENT_DATE NOT NULL,
    last_update  timestamp without time zone DEFAULT now(),
    active       smallint GENERATED ALWAYS AS (
        CASE WHEN (activebool IS TRUE) THEN 1 ELSE 0 END
    ) STORED
);

-- 7. language
CREATE TABLE public.language (
    language_id  integer DEFAULT nextval('public.language_language_id_seq'::regclass) NOT NULL,
    name         character(20) NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 8. actor
CREATE TABLE public.actor (
    actor_id     integer DEFAULT nextval('public.actor_actor_id_seq'::regclass) NOT NULL,
    first_name   character varying(45) NOT NULL,
    last_name    character varying(45) NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 9. category
CREATE TABLE public.category (
    category_id  integer DEFAULT nextval('public.category_category_id_seq'::regclass) NOT NULL,
    name         character varying(25) NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 10. film
CREATE TABLE public.film (
    film_id              integer DEFAULT nextval('public.film_film_id_seq'::regclass) NOT NULL,
    title                character varying(255) NOT NULL,
    description          text,
    release_year         public.year,
    language_id          smallint NOT NULL,
    original_language_id smallint,
    rental_duration      smallint DEFAULT 3 NOT NULL,
    rental_rate          numeric(4,2) DEFAULT 4.99 NOT NULL,
    length               smallint,
    replacement_cost     numeric(5,2) DEFAULT 19.99 NOT NULL,
    rating               public.mpaa_rating DEFAULT 'G'::public.mpaa_rating,
    last_update          timestamp without time zone DEFAULT now() NOT NULL,
    special_features     text[],
    fulltext             tsvector NOT NULL,
    revenue_projection   numeric(5,2) GENERATED ALWAYS AS (((rental_duration)::numeric * rental_rate)) STORED
);

-- 11. film_actor (junction)
CREATE TABLE public.film_actor (
    actor_id     smallint NOT NULL,
    film_id      smallint NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 12. film_category (junction)
CREATE TABLE public.film_category (
    film_id      smallint NOT NULL,
    category_id  smallint NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 13. inventory
CREATE TABLE public.inventory (
    inventory_id integer DEFAULT nextval('public.inventory_inventory_id_seq'::regclass) NOT NULL,
    film_id      smallint NOT NULL,
    store_id     smallint NOT NULL,
    last_update  timestamp without time zone DEFAULT now() NOT NULL
);

-- 14. rental
CREATE TABLE public.rental (
    rental_id     integer DEFAULT nextval('public.rental_rental_id_seq'::regclass) NOT NULL,
    inventory_id  integer NOT NULL,
    customer_id   smallint NOT NULL,
    staff_id      smallint NOT NULL,
    last_update   timestamp without time zone DEFAULT now() NOT NULL,
    rental_period tsrange DEFAULT tsrange((now())::timestamp without time zone, NULL::timestamp without time zone) NOT NULL
);

-- 15. payment (partitioned by payment_date range)
CREATE TABLE public.payment (
    payment_id    integer DEFAULT nextval('public.payment_payment_id_seq'::regclass) NOT NULL,
    customer_id   smallint NOT NULL,
    staff_id      smallint NOT NULL,
    rental_id     integer NOT NULL,
    amount        numeric(5,2) NOT NULL,
    payment_date  timestamp without time zone NOT NULL
) PARTITION BY RANGE (payment_date);

-- 15a. payment partitions
CREATE TABLE public.payment_p2007_01 PARTITION OF public.payment
    FOR VALUES FROM ('2007-01-01') TO ('2007-02-01');

CREATE TABLE public.payment_p2007_02 PARTITION OF public.payment
    FOR VALUES FROM ('2007-02-01') TO ('2007-03-01');

CREATE TABLE public.payment_p2007_03 PARTITION OF public.payment
    FOR VALUES FROM ('2007-03-01') TO ('2007-04-01');

CREATE TABLE public.payment_p2007_04 PARTITION OF public.payment
    FOR VALUES FROM ('2007-04-01') TO ('2007-05-01');

CREATE TABLE public.payment_p2007_05 PARTITION OF public.payment
    FOR VALUES FROM ('2007-05-01') TO ('2007-06-01');

CREATE TABLE public.payment_p2007_06 PARTITION OF public.payment
    FOR VALUES FROM ('2007-06-01') TO ('2007-07-01');

CREATE TABLE public.payment_p2007_07_max PARTITION OF public.payment
    FOR VALUES FROM ('2007-07-01') TO (MAXVALUE);

CREATE TABLE public.payment_p0000_default PARTITION OF public.payment DEFAULT;

-- ══════════════════════════════════════════════════════
--  PRIMARY KEYS
-- ══════════════════════════════════════════════════════

ALTER TABLE ONLY public.country      ADD CONSTRAINT country_pkey      PRIMARY KEY (country_id);
ALTER TABLE ONLY public.city         ADD CONSTRAINT city_pkey         PRIMARY KEY (city_id);
ALTER TABLE ONLY public.address      ADD CONSTRAINT address_pkey      PRIMARY KEY (address_id);
ALTER TABLE ONLY public.store        ADD CONSTRAINT store_pkey        PRIMARY KEY (store_id);
ALTER TABLE ONLY public.staff        ADD CONSTRAINT staff_pkey        PRIMARY KEY (staff_id);
ALTER TABLE ONLY public.customer     ADD CONSTRAINT customer_pkey     PRIMARY KEY (customer_id);
ALTER TABLE ONLY public.language     ADD CONSTRAINT language_pkey     PRIMARY KEY (language_id);
ALTER TABLE ONLY public.actor        ADD CONSTRAINT actor_pkey_incl   PRIMARY KEY (actor_id) INCLUDE (first_name, last_name);
ALTER TABLE ONLY public.category     ADD CONSTRAINT category_pkey     PRIMARY KEY (category_id);
ALTER TABLE ONLY public.film         ADD CONSTRAINT film_pkey         PRIMARY KEY (film_id);
ALTER TABLE ONLY public.film_actor   ADD CONSTRAINT film_actor_pkey   PRIMARY KEY (actor_id, film_id);
ALTER TABLE ONLY public.film_category ADD CONSTRAINT film_category_pkey PRIMARY KEY (film_id, category_id);
ALTER TABLE ONLY public.inventory    ADD CONSTRAINT inventory_pkey    PRIMARY KEY (inventory_id);
ALTER TABLE ONLY public.rental       ADD CONSTRAINT rental_pkey       PRIMARY KEY (rental_id);

-- payment partition PKs
ALTER TABLE ONLY public.payment_p2007_01 ADD CONSTRAINT idx_pk_payment_p2007_01_payment_id PRIMARY KEY (payment_id);
ALTER TABLE ONLY public.payment_p2007_02 ADD CONSTRAINT idx_pk_payment_p2007_02_payment_id PRIMARY KEY (payment_id);
ALTER TABLE ONLY public.payment_p2007_03 ADD CONSTRAINT idx_pk_payment_p2007_03_payment_id PRIMARY KEY (payment_id);
ALTER TABLE ONLY public.payment_p2007_04 ADD CONSTRAINT idx_pk_payment_p2007_04_payment_id PRIMARY KEY (payment_id);
ALTER TABLE ONLY public.payment_p2007_05 ADD CONSTRAINT idx_pk_payment_p2007_05_payment_id PRIMARY KEY (payment_id);
ALTER TABLE ONLY public.payment_p2007_06 ADD CONSTRAINT idx_pk_payment_p2007_06_payment_id PRIMARY KEY (payment_id);

-- ══════════════════════════════════════════════════════
--  INDEXES
-- ══════════════════════════════════════════════════════

CREATE INDEX idx_actor_last_name          ON public.actor        USING btree (last_name);
CREATE INDEX idx_fk_address_id            ON public.customer     USING btree (address_id);
CREATE INDEX idx_fk_city_id               ON public.address      USING btree (city_id);
CREATE INDEX idx_fk_country_id            ON public.city         USING btree (country_id);
CREATE INDEX idx_fk_film_id               ON public.film_actor   USING btree (film_id);
CREATE INDEX idx_fk_inventory_id          ON public.rental       USING btree (inventory_id);
CREATE INDEX idx_fk_language_id           ON public.film         USING btree (language_id);
CREATE INDEX idx_fk_original_language_id  ON public.film         USING btree (original_language_id);
CREATE INDEX idx_fk_store_id              ON public.customer     USING btree (store_id);
CREATE INDEX idx_last_name                ON public.customer     USING btree (last_name);
CREATE INDEX idx_store_id_film_id         ON public.inventory    USING btree (store_id, film_id);
CREATE INDEX idx_title                    ON public.film         USING btree (title);
CREATE UNIQUE INDEX idx_unq_manager_staff_id ON public.store     USING btree (manager_staff_id);
CREATE INDEX film_fulltext_idx            ON public.film         USING gist (fulltext);

-- payment partition indexes
CREATE INDEX idx_fk_payment_p2007_01_customer_id ON public.payment_p2007_01 USING btree (customer_id);
CREATE INDEX idx_fk_payment_p2007_01_staff_id    ON public.payment_p2007_01 USING btree (staff_id);
CREATE INDEX idx_fk_payment_p2007_02_customer_id ON public.payment_p2007_02 USING btree (customer_id);
CREATE INDEX idx_fk_payment_p2007_02_staff_id    ON public.payment_p2007_02 USING btree (staff_id);
CREATE INDEX idx_fk_payment_p2007_03_customer_id ON public.payment_p2007_03 USING btree (customer_id);
CREATE INDEX idx_fk_payment_p2007_03_staff_id    ON public.payment_p2007_03 USING btree (staff_id);
CREATE INDEX idx_fk_payment_p2007_04_customer_id ON public.payment_p2007_04 USING btree (customer_id);
CREATE INDEX idx_fk_payment_p2007_04_staff_id    ON public.payment_p2007_04 USING btree (staff_id);
CREATE INDEX idx_fk_payment_p2007_05_customer_id ON public.payment_p2007_05 USING btree (customer_id);
CREATE INDEX idx_fk_payment_p2007_05_staff_id    ON public.payment_p2007_05 USING btree (staff_id);
CREATE INDEX idx_fk_payment_p2007_06_customer_id ON public.payment_p2007_06 USING btree (customer_id);
CREATE INDEX idx_fk_payment_p2007_06_staff_id    ON public.payment_p2007_06 USING btree (staff_id);

-- ══════════════════════════════════════════════════════
--  FOREIGN KEYS
-- ══════════════════════════════════════════════════════

-- city → country
ALTER TABLE ONLY public.city
    ADD CONSTRAINT city_country_id_fkey FOREIGN KEY (country_id) REFERENCES public.country(country_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- address → city
ALTER TABLE ONLY public.address
    ADD CONSTRAINT address_city_id_fkey FOREIGN KEY (city_id) REFERENCES public.city(city_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- store → address
ALTER TABLE ONLY public.store
    ADD CONSTRAINT store_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.address(address_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- store → staff (manager)
ALTER TABLE ONLY public.store
    ADD CONSTRAINT store_manager_staff_id_fkey FOREIGN KEY (manager_staff_id) REFERENCES public.staff(staff_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- staff → address
ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.address(address_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- staff → store
ALTER TABLE ONLY public.staff
    ADD CONSTRAINT staff_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.store(store_id);

-- customer → store
ALTER TABLE ONLY public.customer
    ADD CONSTRAINT customer_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.store(store_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- customer → address
ALTER TABLE ONLY public.customer
    ADD CONSTRAINT customer_address_id_fkey FOREIGN KEY (address_id) REFERENCES public.address(address_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- film → language
ALTER TABLE ONLY public.film
    ADD CONSTRAINT film_language_id_fkey FOREIGN KEY (language_id) REFERENCES public.language(language_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- film → language (original)
ALTER TABLE ONLY public.film
    ADD CONSTRAINT film_original_language_id_fkey FOREIGN KEY (original_language_id) REFERENCES public.language(language_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- film_actor → actor
ALTER TABLE ONLY public.film_actor
    ADD CONSTRAINT film_actor_actor_id_fkey FOREIGN KEY (actor_id) REFERENCES public.actor(actor_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- film_actor → film
ALTER TABLE ONLY public.film_actor
    ADD CONSTRAINT film_actor_film_id_fkey FOREIGN KEY (film_id) REFERENCES public.film(film_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- film_category → film
ALTER TABLE ONLY public.film_category
    ADD CONSTRAINT film_category_film_id_fkey FOREIGN KEY (film_id) REFERENCES public.film(film_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- film_category → category
ALTER TABLE ONLY public.film_category
    ADD CONSTRAINT film_category_category_id_fkey FOREIGN KEY (category_id) REFERENCES public.category(category_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- inventory → film
ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_film_id_fkey FOREIGN KEY (film_id) REFERENCES public.film(film_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- inventory → store
ALTER TABLE ONLY public.inventory
    ADD CONSTRAINT inventory_store_id_fkey FOREIGN KEY (store_id) REFERENCES public.store(store_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- rental → inventory
ALTER TABLE ONLY public.rental
    ADD CONSTRAINT rental_inventory_id_fkey FOREIGN KEY (inventory_id) REFERENCES public.inventory(inventory_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- rental → customer
ALTER TABLE ONLY public.rental
    ADD CONSTRAINT rental_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- rental → staff
ALTER TABLE ONLY public.rental
    ADD CONSTRAINT rental_staff_id_fkey FOREIGN KEY (staff_id) REFERENCES public.staff(staff_id) ON UPDATE CASCADE ON DELETE RESTRICT;

-- payment partitions → customer, rental, staff
ALTER TABLE ONLY public.payment_p2007_01 ADD CONSTRAINT payment_p2007_01_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id);
ALTER TABLE ONLY public.payment_p2007_01 ADD CONSTRAINT payment_p2007_01_rental_id_fkey   FOREIGN KEY (rental_id)   REFERENCES public.rental(rental_id);
ALTER TABLE ONLY public.payment_p2007_01 ADD CONSTRAINT payment_p2007_01_staff_id_fkey    FOREIGN KEY (staff_id)    REFERENCES public.staff(staff_id);

ALTER TABLE ONLY public.payment_p2007_02 ADD CONSTRAINT payment_p2007_02_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id);
ALTER TABLE ONLY public.payment_p2007_02 ADD CONSTRAINT payment_p2007_02_rental_id_fkey   FOREIGN KEY (rental_id)   REFERENCES public.rental(rental_id);
ALTER TABLE ONLY public.payment_p2007_02 ADD CONSTRAINT payment_p2007_02_staff_id_fkey    FOREIGN KEY (staff_id)    REFERENCES public.staff(staff_id);

ALTER TABLE ONLY public.payment_p2007_03 ADD CONSTRAINT payment_p2007_03_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id);
ALTER TABLE ONLY public.payment_p2007_03 ADD CONSTRAINT payment_p2007_03_rental_id_fkey   FOREIGN KEY (rental_id)   REFERENCES public.rental(rental_id);
ALTER TABLE ONLY public.payment_p2007_03 ADD CONSTRAINT payment_p2007_03_staff_id_fkey    FOREIGN KEY (staff_id)    REFERENCES public.staff(staff_id);

ALTER TABLE ONLY public.payment_p2007_04 ADD CONSTRAINT payment_p2007_04_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id);
ALTER TABLE ONLY public.payment_p2007_04 ADD CONSTRAINT payment_p2007_04_rental_id_fkey   FOREIGN KEY (rental_id)   REFERENCES public.rental(rental_id);
ALTER TABLE ONLY public.payment_p2007_04 ADD CONSTRAINT payment_p2007_04_staff_id_fkey    FOREIGN KEY (staff_id)    REFERENCES public.staff(staff_id);

ALTER TABLE ONLY public.payment_p2007_05 ADD CONSTRAINT payment_p2007_05_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id);
ALTER TABLE ONLY public.payment_p2007_05 ADD CONSTRAINT payment_p2007_05_rental_id_fkey   FOREIGN KEY (rental_id)   REFERENCES public.rental(rental_id);
ALTER TABLE ONLY public.payment_p2007_05 ADD CONSTRAINT payment_p2007_05_staff_id_fkey    FOREIGN KEY (staff_id)    REFERENCES public.staff(staff_id);

ALTER TABLE ONLY public.payment_p2007_06 ADD CONSTRAINT payment_p2007_06_customer_id_fkey FOREIGN KEY (customer_id) REFERENCES public.customer(customer_id);
ALTER TABLE ONLY public.payment_p2007_06 ADD CONSTRAINT payment_p2007_06_rental_id_fkey   FOREIGN KEY (rental_id)   REFERENCES public.rental(rental_id);
ALTER TABLE ONLY public.payment_p2007_06 ADD CONSTRAINT payment_p2007_06_staff_id_fkey    FOREIGN KEY (staff_id)    REFERENCES public.staff(staff_id);

-- ══════════════════════════════════════════════════════
--  DONE – 15 tables + 8 payment partitions ready.
-- ══════════════════════════════════════════════════════
