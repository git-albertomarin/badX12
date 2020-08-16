# -*- coding: utf-8 -*-
from pathlib import Path
from typing import List, Optional

from badx12.document import EDIDocument, InterchangeHeader, InterchangeTrailer
from badx12.document.datastructures import Element, Segment
from badx12.document.group import Group, GroupHeader, GroupTrailer
from badx12.document.transaction_set import (
    TransactionSet,
    TransactionSetHeader,
    TransactionSetTrailer,
)
from badx12.exceptions import InvalidFileTypeError, SegmentTerminatorNotFoundError


class Parser:
    def __init__(self, document: Optional[str] = None):
        """Create a new Parser
        :param document:  The text or file to parse into an EDI document.
        """
        self.document: EDIDocument = EDIDocument()
        self.document_text: str = ""

        if document is not None:
            self.parse_document(document)

    def parse_document(self, document: str) -> EDIDocument:
        """Parse the text document into an object
        :param document:  The text or file to parse into an EDI document.
        """
        self.document_text = self._validate_document(document)
        self.document.text = self.document_text

        if self.document_text.startswith(EDIDocument().interchange.header.id.name):
            self._parse_interchange_header()
            self._separate_and_route_segments()

        else:
            found_segment: str = self.document_text[:3]
            raise InvalidFileTypeError(
                segment=found_segment,
                msg=f"""Expected Element Envelope: {EDIDocument().interchange.header.id.name} but found Element
                Envelope: {found_segment}.\n The length of the expected segment is:
                {str(len(EDIDocument().interchange.header.id.name))} the length of the segment found was:
                {str(len(found_segment))}""",
            )

        return self.document

    def _validate_document(self, document: str) -> str:
        try:
            is_file: bool = Path(document).is_file()
        except AttributeError and OSError:
            is_file = False

        if not isinstance(document, str) and not is_file:
            raise TypeError(
                f"""{self.parse_document.__name__}() expects document to be of type str or x12 file,
                got {type(document)}"""
            )

        if is_file:
            with open(document, "r") as x12File:
                document = x12File.read().strip()

        return document.replace("\n", "").strip()

    def _parse_interchange_header(self) -> None:
        """Parse the interchange header segment"""
        header: InterchangeHeader = self.document.interchange.header
        self.document.config.element_separator = self.document_text[3:4]
        header_field_list: List[str] = self.document_text.split(
            self.document.config.element_separator
        )

        for index, isa in enumerate(header_field_list):
            if index == 12:
                self.document.config.version = isa
            if index <= 15:
                header.fields[index].content = isa
            if index == 16:
                last_header_field: str = header_field_list[16]

                # The sub-element separator is always the first character in this element.
                header.isa16.content = last_header_field[0:1]

                if last_header_field[1:2]:
                    self.document.config.segment_terminator = last_header_field[1:2]
                else:
                    raise SegmentTerminatorNotFoundError(
                        msg="The segment terminator is not present in the Interchange Header, can't parse file."
                    )

    def _separate_and_route_segments(self) -> None:
        """Handles separating all the segments"""
        self.segment_list = self.document_text.split(
            self.document.config.segment_terminator
        )
        for segment in self.segment_list:
            self._route_segment_to_parser(segment)

    def _route_segment_to_parser(self, segment: str) -> None:
        """Take a generic segment and determine what segment to parse it as
        :param segment:
        """
        if segment.startswith(InterchangeHeader().id.name):
            pass
        elif segment.startswith(GroupHeader().id.name):
            self._parse_group_header(segment)
        elif segment.startswith(GroupTrailer().id.name):
            self._parse_group_trailer(segment)
        elif segment.startswith(TransactionSetHeader().id.name):
            self._parse_transaction_set_header(segment)
        elif segment.startswith(TransactionSetTrailer().id.name):
            self._parse_transaction_set_trailer(segment)
        elif segment.startswith(EDIDocument().interchange.trailer.id.name):
            self._parse_interchange_trailer(segment)
        else:
            self._parse_unknown_body(segment)

    def _parse_segment(self, segment: Segment, segment_field_list: List[str]) -> None:
        """Generically parse segments
        :param segment: the segment to insert the values.
        :param segment_field_list: the list of segments to parse.
        """
        for index, value in enumerate(segment_field_list):
            segment.fields[index].content = value

    def _parse_group_header(self, segment: str) -> None:
        """Parse the group header"""
        self.current_group = Group()
        header: GroupHeader = GroupHeader()
        header_field_list: List[str] = segment.split(
            self.document.config.element_separator
        )
        self._parse_segment(header, header_field_list)
        self.current_group.header = header

    def _parse_group_trailer(self, segment: str) -> None:
        """Parse the group trailer"""
        trailer: GroupTrailer = GroupTrailer()
        trailer_field_list: List[str] = segment.split(
            self.document.config.element_separator
        )
        self._parse_segment(trailer, trailer_field_list)
        self.current_group.trailer = trailer
        self.document.interchange.groups.append(self.current_group)

    def _parse_interchange_trailer(self, segment: str) -> None:
        """Parse the interchange trailer segment"""
        trailer: InterchangeTrailer = self.document.interchange.trailer
        trailer_field_list: List[str] = segment.split(
            self.document.config.element_separator
        )
        self._parse_segment(trailer, trailer_field_list)

    def _parse_transaction_set_header(self, segment: str) -> None:
        """Parse transaction set header
        Creates a new transaction set and set it as the current transaction set.
        """
        self.current_transaction = TransactionSet()
        transaction_header: TransactionSetHeader = TransactionSetHeader()
        header_field_list: List[str] = segment.split(
            self.document.config.element_separator
        )
        self._parse_segment(transaction_header, header_field_list)
        self.current_transaction.header = transaction_header

    def _parse_transaction_set_trailer(self, segment: str) -> None:
        """Parse the transaction set trailer.
        Adds the completed transaction to a edi document.
        """
        transaction_trailer = TransactionSetTrailer()
        trailer_field_list: List[str] = segment.split(
            self.document.config.element_separator
        )
        self._parse_segment(transaction_trailer, trailer_field_list)
        self.current_transaction.trailer = transaction_trailer
        self.current_group.transaction_sets.append(self.current_transaction)

    def _parse_unknown_body(self, segment: str) -> None:
        if segment:
            generic_segment: Segment = Segment()
            generic_field_list: List[str] = segment.split(
                self.document.config.element_separator
            )
            self._parse__unknown_segment(generic_segment, generic_field_list)
            try:
                self.current_transaction.transaction_body.append(generic_segment)
            except AttributeError:
                pass

    def _parse__unknown_segment(
        self, segment: Segment, segment_field_list: List[str]
    ) -> None:
        """Generically parse unknown segments by creating a
        new element and appending it to the segment.
        :param segment: the segment to append the values.
        :param segment_field_list: the list of segments to parse.
        """
        for index, value in enumerate(segment_field_list):
            element: Element = self._create_generic_element(
                index, value, segment_field_list[0]
            )
            segment.fields.append(element)

        segment.id = segment.fields[0]
        segment.field_count = len(segment.fields)

    def _create_generic_element(self, index: int, value: str, name: str) -> Element:
        """
        Create a generic element based on the data found. Populate all the
        fields so that validation will pass.
        :param index: the position of the element for providing a name.
        :param value: the content for the element being created.
        :return: a generic element.
        """
        element: Element = Element()
        element.name = name

        if index > 0:
            element.name = f"{name}{str(index).zfill(2)}"

        element.content = value
        element.description = "A generic element created by the parser"
        element.required = False
        length: int = len(value)
        element.min_length = length
        element.max_length = length
        return element
