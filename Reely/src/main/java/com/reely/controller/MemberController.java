package com.reely.controller;

import com.reely.dto.MemberDto;
import com.reely.service.MemberService;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

@RestController
@RequestMapping("/api/member")
public class MemberController {

    private final MemberService memberService;

    @Autowired
    public MemberController(MemberService memberService) {
        this.memberService = memberService;
    }

    @PostMapping("/duplicate-id")
    public ResponseEntity<Boolean> duplicateId(@RequestBody MemberDto memberDto) {
        Boolean result = memberService.findMemberByMemberId(memberDto);
        return new ResponseEntity<>(result, HttpStatus.OK);
    }

    @PostMapping("/join")
    public ResponseEntity<Integer> join(@RequestBody MemberDto memberDto) {
        Integer result = memberService.insertMember(memberDto);
        return new ResponseEntity<>(result, HttpStatus.OK);
    }

    @GetMapping("/test")
    public ResponseEntity<String> test() {
        return new ResponseEntity<>("성공", HttpStatus.OK);
    }

}
