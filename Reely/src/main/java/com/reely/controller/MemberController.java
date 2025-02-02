package com.reely.controller;

import com.reely.dto.MemberDto;
import com.reely.service.MemberService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/member")
public class MemberController {

    private final MemberService memberService;

    @Autowired
    public MemberController(MemberService memberService) {
        this.memberService = memberService;
    }

    @PostMapping("/duplicate-id")
    public ResponseEntity<Boolean> join(@RequestBody MemberDto memberDto) {
        Boolean result = memberService.findMemberByMemberId(memberDto);
        return new ResponseEntity<>(result, HttpStatus.OK);
    }
}
